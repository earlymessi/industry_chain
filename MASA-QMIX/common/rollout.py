import numpy as np
import torch
from torch.distributions import one_hot_categorical
from common.data_file_utils import get_data_file_path, get_data_dir
import time


class RolloutWorker:
    def __init__(self, env, agents, args):
        self.env = env
        self.agents = agents
        self.episode_limit = args.episode_limit
        self.n_actions = args.n_actions
        self.n_agents = args.n_agents
        self.state_shape = args.state_shape
        self.obs_shape = args.obs_shape
        self.args = args

        self.epsilon = args.epsilon
        self.anneal_epsilon = args.anneal_epsilon
        self.min_epsilon = args.min_epsilon
        
        # 确定是否为训练模式（通过args.learn判断）
        self.is_training = args.learn if hasattr(args, 'learn') else True
        
        print('Init RolloutWorker')

    def generate_episode(self, episode_num=None, evaluate=False):
        # 使用新的文件路径，区分训练/评估和智能体数量
        is_training_mode = self.is_training and not evaluate
        havealook_path = get_data_file_path(
            get_data_dir(),
            'havealook.txt',
            self.n_agents,
            is_training=is_training_mode
        )
        with open(havealook_path, "a") as f:
            print("----", file=f)
        if self.args.replay_dir != '' and evaluate and episode_num == 0:  # prepare for save replay of evaluation
            self.env.close()
        # 开始收集与环境交互的情况
        # 收集了8个东西？
        o, u, r, s, avail_u, u_onehot, terminate, padded = [], [], [], [], [], [], [], []
        # episode_rewards = 0
        self.env.reset()
        terminated = False
        win_tag = False
        step = 0
        episode_reward = 0  # cumulative rewards
        last_action = np.zeros((self.args.n_agents, self.args.n_actions))
        self.agents.policy.init_hidden(1)

        # epsilon
        # 如果评估模式下rollout worker的epsilon被设置为非0值，则使用该值（用于引入随机性）
        # 否则，评估模式下使用0（确定性策略）
        if evaluate:
            # 检查是否有自定义的评估epsilon值（通过设置self.epsilon来传递）
            epsilon = self.epsilon if hasattr(self, 'epsilon') and self.epsilon > 0 else 0
        else:
            epsilon = self.epsilon
        if self.args.epsilon_anneal_scale == 'episode':
            epsilon = epsilon - self.anneal_epsilon if epsilon > self.min_epsilon else epsilon
        if self.args.epsilon_anneal_scale == 'epoch':
            if episode_num == 0:
                epsilon = epsilon - self.anneal_epsilon if epsilon > self.min_epsilon else epsilon

        # sample z for maven
        if self.args.alg == 'maven':
            state = self.env.get_state()
            state = torch.tensor(state, dtype=torch.float32)
            if self.args.cuda:
                state = state.cuda()
            z_prob = self.agents.policy.z_policy(state)
            maven_z = one_hot_categorical.OneHotCategorical(z_prob).sample()
            maven_z = list(maven_z.cpu())

        for_gantt = []
        while not terminated and step < self.episode_limit:
            # time.sleep(0.2)
            obs = self.env.get_obs()  # [[],[],...]
            state = self.env.get_state() # []
            actions, avail_actions, actions_onehot = [], [], []

            for agent_id in range(self.n_agents):
                avail_action = self.env.get_avail_agent_actions(agent_id)
                # print(avail_action)
                # # 判断是不是所有动作都不可选
                # assert avail_action[-1] == 1
                action = self.agents.choose_action(obs[agent_id], last_action[agent_id], agent_id,
                                                   avail_action, epsilon, evaluate)

                if action != 18 and action != 19 and action != 20:  # 更新环境状态
                    self.env.has_chosen_action(action, agent_id)

                # generate onehot vector of th action
                action_onehot = np.zeros(self.args.n_actions)
                action_onehot[action] = 1
                actions.append(action)
                actions_onehot.append(action_onehot)
                avail_actions.append(avail_action)
                last_action[agent_id] = action_onehot

            reward, terminated, info = self.env.step(actions)
            win_tag = True if terminated and 'battle_won' in info and info['battle_won'] else False
            o.append(obs)
            s.append(state)
            # actions = np.array(actions)  # 将动作转化为数组
            u.append(np.reshape(actions, [self.n_agents, 1]))
            u_onehot.append(actions_onehot)
            # avail_actions = np.array(avail_actions)
            avail_u.append(avail_actions)
            r.append([reward])
            terminate.append([terminated])
            padded.append([0.])
            episode_reward += reward
            step += 1
            if self.args.epsilon_anneal_scale == 'step':
                epsilon = epsilon - self.anneal_epsilon if epsilon > self.min_epsilon else epsilon
            # 存储gantt的记录（无论是否终止，都保存当前的调度数据）
            # 如果episode正常终止，保存完整的调度数据；如果未终止，也保存部分数据
            if terminated:
                for_gantt = info.get("episodes_situation", [])
            # 即使未终止，也保存当前的调度数据（如果有的话）
            elif "episodes_situation" in info and len(info["episodes_situation"]) > 0:
                for_gantt = info["episodes_situation"]

        # 记录奖励值和时间的变化
        # 评估模式下写入不带前缀的文件（与api_server.py读取路径一致）
        is_training_mode = self.is_training and not evaluate
        accumulated_rewards_path = get_data_file_path(
            get_data_dir(),
            'accumulated_rewards.txt',
            self.n_agents,
            is_training=False  # 评估文件不使用前缀
        )
        times_path = get_data_file_path(
            get_data_dir(),
            'times.txt',
            self.n_agents,
            is_training=False  # 评估文件不使用前缀
        )
        with open(accumulated_rewards_path, "a") as f:
            # 确保episode_reward是Python标量，避免tensor输出
            reward_value = float(episode_reward) if hasattr(episode_reward, '__float__') else episode_reward
            print(reward_value, file=f)
        with open(times_path, "a") as f:
            print(info["time"], file=f)

        # last obs
        o.append(obs)
        s.append(state)
        o_next = o[1:]
        s_next = s[1:]
        o = o[:-1]
        s = s[:-1]
        # get avail_action for last obs，because target_q needs avail_action in training
        avail_actions = []
        for agent_id in range(self.n_agents):
            avail_action = self.env.get_avail_agent_actions(agent_id)
            avail_actions.append(avail_action)
        avail_u.append(avail_actions)
        avail_u_next = avail_u[1:]
        avail_u = avail_u[:-1]

        if self.args.havelook:
            # 使用新的文件路径
            is_training_mode = self.is_training and not evaluate
            havealook_path = get_data_file_path(
                get_data_dir(),
                'havealook.txt',
                self.n_agents,
                is_training=is_training_mode
            )
            with open(havealook_path, "a") as f:
                for num in range(len(o)):
                    print("o:", o[num], file=f)
                    print("s:", s[num], file=f)
                    print("u:", u[num], file=f)
                    print("avail:", avail_u[num], file=f)
                    print("r:", r[num],"\n", file=f)


        # if step < self.episode_limit，padding
        for i in range(step, self.episode_limit):
            o.append(np.zeros((self.n_agents, self.obs_shape)))
            u.append(np.zeros([self.n_agents, 1]))
            s.append(np.zeros(self.state_shape))
            r.append([0.])
            o_next.append(np.zeros((self.n_agents, self.obs_shape)))
            s_next.append(np.zeros(self.state_shape))
            u_onehot.append(np.zeros((self.n_agents, self.n_actions)))
            avail_u.append(np.zeros((self.n_agents, self.n_actions)))
            avail_u_next.append(np.zeros((self.n_agents, self.n_actions)))
            padded.append([1.])
            terminate.append([1.])  # 如果没有padding的情况下是没有terminal的

        episode = dict(o=o.copy(),
                       s=s.copy(),
                       u=u.copy(),
                       r=r.copy(),
                       avail_u=avail_u.copy(),
                       o_next=o_next.copy(),
                       s_next=s_next.copy(),
                       avail_u_next=avail_u_next.copy(),
                       u_onehot=u_onehot.copy(),
                       padded=padded.copy(),
                       terminated=terminate.copy()
                       )
        # add episode dim
        for key in episode.keys():
            episode[key] = np.array([episode[key]])
        if not evaluate:
            self.epsilon = epsilon
        if self.args.alg == 'maven':
            episode['z'] = np.array([maven_z.copy()])
        if evaluate and episode_num == self.args.evaluate_epoch - 1 and self.args.replay_dir != '':
            self.env.save_replay()
            self.env.close()
        # 获取episode总时间
        episode_time = info.get("time", 0) if info else 0
        return episode, episode_reward, win_tag, for_gantt, episode_time


# RolloutWorker for communication
class CommRolloutWorker:
    def __init__(self, env, agents, args):
        self.env = env
        self.agents = agents
        self.episode_limit = args.episode_limit
        self.n_actions = args.n_actions
        self.n_agents = args.n_agents
        self.state_shape = args.state_shape
        self.obs_shape = args.obs_shape
        self.args = args

        self.epsilon = args.epsilon
        self.anneal_epsilon = args.anneal_epsilon
        self.min_epsilon = args.min_epsilon
        
        # 确定是否为训练模式（通过args.learn判断）
        self.is_training = args.learn if hasattr(args, 'learn') else True
        
        print('Init CommRolloutWorker')

    def generate_episode(self, episode_num=None, evaluate=False):
        if self.args.replay_dir != '' and evaluate and episode_num == 0:  # prepare for save replay
            self.env.close()
        o, u, r, s, avail_u, u_onehot, terminate, padded = [], [], [], [], [], [], [], []
        self.env.reset()
        terminated = False
        win_tag = False
        step = 0
        episode_reward = 0
        last_action = np.zeros((self.args.n_agents, self.args.n_actions))
        self.agents.policy.init_hidden(1)
        epsilon = 0 if evaluate else self.epsilon
        if self.args.epsilon_anneal_scale == 'episode':
            epsilon = epsilon - self.anneal_epsilon if epsilon > self.min_epsilon else epsilon
        if self.args.epsilon_anneal_scale == 'epoch':
            if episode_num == 0:
                epsilon = epsilon - self.anneal_epsilon if epsilon > self.min_epsilon else epsilon
        while not terminated and step < self.episode_limit:
            # time.sleep(0.2)
            obs = self.env.get_obs()
            state = self.env.get_state()
            actions, avail_actions, actions_onehot = [], [], []

            # get the weights of all actions for all agents
            weights = self.agents.get_action_weights(np.array(obs), last_action)

            # choose action for each agent
            for agent_id in range(self.n_agents):
                avail_action = self.env.get_avail_agent_actions(agent_id)
                action = self.agents.choose_action(weights[agent_id], avail_action, epsilon, evaluate)

                # generate onehot vector of th action
                action_onehot = np.zeros(self.args.n_actions)
                action_onehot[action] = 1
                actions.append(action)
                actions_onehot.append(action_onehot)
                avail_actions.append(avail_action)
                last_action[agent_id] = action_onehot

            reward, terminated, info = self.env.step(actions)
            win_tag = True if terminated and 'battle_won' in info and info['battle_won'] else False
            o.append(obs)
            s.append(state)
            u.append(np.reshape(actions, [self.n_agents, 1]))
            u_onehot.append(actions_onehot)
            avail_u.append(avail_actions)
            r.append([reward])
            terminate.append([terminated])
            padded.append([0.])
            episode_reward += reward
            step += 1
            # if terminated:
            #     time.sleep(1)
            if self.args.epsilon_anneal_scale == 'step':
                epsilon = epsilon - self.anneal_epsilon if epsilon > self.min_epsilon else epsilon
        # last obs
        o.append(obs)
        s.append(state)
        o_next = o[1:]
        s_next = s[1:]
        o = o[:-1]
        s = s[:-1]
        # get avail_action for last obs，because target_q needs avail_action in training
        avail_actions = []
        for agent_id in range(self.n_agents):
            avail_action = self.env.get_avail_agent_actions(agent_id)
            avail_actions.append(avail_action)
        avail_u.append(avail_actions)
        avail_u_next = avail_u[1:]
        avail_u = avail_u[:-1]

        # if step < self.episode_limit，padding
        for i in range(step, self.episode_limit):
            o.append(np.zeros((self.n_agents, self.obs_shape)))
            u.append(np.zeros([self.n_agents, 1]))
            s.append(np.zeros(self.state_shape))
            r.append([0.])
            o_next.append(np.zeros((self.n_agents, self.obs_shape)))
            s_next.append(np.zeros(self.state_shape))
            u_onehot.append(np.zeros((self.n_agents, self.n_actions)))
            avail_u.append(np.zeros((self.n_agents, self.n_actions)))
            avail_u_next.append(np.zeros((self.n_agents, self.n_actions)))
            padded.append([1.])
            terminate.append([1.])

        episode = dict(o=o.copy(),
                       s=s.copy(),
                       u=u.copy(),
                       r=r.copy(),
                       avail_u=avail_u.copy(),
                       o_next=o_next.copy(),
                       s_next=s_next.copy(),
                       avail_u_next=avail_u_next.copy(),
                       u_onehot=u_onehot.copy(),
                       padded=padded.copy(),
                       terminated=terminate.copy()
                       )
        # add episode dim
        for key in episode.keys():
            episode[key] = np.array([episode[key]])
        if not evaluate:
            self.epsilon = epsilon
            # print('Epsilon is ', self.epsilon)
        if evaluate and episode_num == self.args.evaluate_epoch - 1 and self.args.replay_dir != '':
            self.env.save_replay()
            self.env.close()
        return episode, episode_reward, win_tag, [], 0
