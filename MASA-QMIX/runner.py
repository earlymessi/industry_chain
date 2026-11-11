import numpy as np
import os
from common.rollout import RolloutWorker, CommRolloutWorker
from agent.agent import Agents, CommAgents
from common.replay_buffer import ReplayBuffer
from common.data_file_utils import get_data_file_path, get_data_dir
import matplotlib.pyplot as plt
import sys


class Runner:
    def __init__(self, env, args):
        self.env = env

        if args.alg.find('commnet') > -1 or args.alg.find('g2anet') > -1:  # communication agent
            self.agents = CommAgents(args)
            self.rolloutWorker = CommRolloutWorker(env, self.agents, args)
        else:  # no communication agent
            self.agents = Agents(args)
            self.rolloutWorker = RolloutWorker(env, self.agents, args)
        if args.learn and args.alg.find('coma') == -1 and args.alg.find('central_v') == -1 and args.alg.find('reinforce') == -1:  # these 3 algorithms are on-poliy
            self.buffer = ReplayBuffer(args)
        self.args = args
        self.win_rates = []
        self.episode_rewards = []

        # 用来保存plt和pkl
        self.save_path = self.args.result_dir + '/' + args.alg + '/' + args.map
        if not os.path.exists(self.save_path):
            os.makedirs(self.save_path)
        
        # 初始化数据文件路径工具
        # 确定是否为训练模式
        self.is_training = args.learn if hasattr(args, 'learn') else True
        # 智能体数量会在环境初始化后确定，这里先尝试获取
        # 如果环境已经初始化，n_agents应该已经设置
        self.n_agents = args.n_agents if hasattr(args, 'n_agents') and args.n_agents is not None else None

    def run(self, num):
        train_steps = 0
        # print('Run {} start'.format(num))
        r_s = [0]
        for epoch in range(self.args.n_epoch):
            # 显示输出

            text = '\rRun {}, train epoch {}, ave_rewards {}'
            # 确保ave_reward是Python标量，避免tensor输出
            ave_reward = float(sum(r_s) / len(r_s)) if len(r_s) > 0 else 0.0
            sys.stdout.write(text.format(num, epoch, ave_reward))
            sys.stdout.flush()

            # print('Run {}, train epoch {}'.format(num, epoch), flush=False)
            if epoch % self.args.evaluate_cycle == 0 and epoch != 0:
                win_rate, episode_reward = self.evaluate()
                # print('win_rate is ', win_rate)
                self.win_rates.append(win_rate)
                # 确保episode_reward是Python标量，避免tensor输出
                reward_value = float(episode_reward) if hasattr(episode_reward, '__float__') else episode_reward
                print("\nepisode_reward:", reward_value, "epoch:", epoch)
                self.episode_rewards.append(episode_reward)
                # self.plt(num)

            episodes = []
            r_s = []
            all_gantt_data = []  # 收集所有episode的调度数据
            # 收集self.args.n_episodes个episodes
            for episode_idx in range(self.args.n_episodes):
                episode, _, _, for_gantt_data, _ = self.rolloutWorker.generate_episode(episode_idx)
                episodes.append(episode)
                # 确保reward是Python标量，避免tensor输出
                episode_reward_sum = sum(episode['r'][0])[0]
                r_s.append(float(episode_reward_sum) if hasattr(episode_reward_sum, '__float__') else episode_reward_sum)
                # 收集每个episode的调度数据（如果有的话）
                if for_gantt_data is not None and len(for_gantt_data) > 0:
                    all_gantt_data.append(for_gantt_data)
                # print(_)
            # episode的每一项都是一个(1, episode_len, n_agents, 具体维度)四维数组，下面要把所有episode的obs拼在一起
            episode_batch = episodes[0]
            episodes.pop(0)
            for episode in episodes:
                for key in episode_batch.keys():
                    episode_batch[key] = np.concatenate((episode_batch[key], episode[key]), axis=0)
            if self.args.alg.find('coma') > -1 or self.args.alg.find('central_v') > -1 or self.args.alg.find('reinforce') > -1:
                self.agents.train(episode_batch, train_steps, self.rolloutWorker.epsilon)
                train_steps += 1
            else:
                # 这几个类型的算法需要进行buffer的存储
                self.buffer.store_episode(episode_batch)
                for train_step in range(self.args.train_steps):
                    mini_batch = self.buffer.sample(min(self.buffer.current_size, self.args.batch_size))
                    self.agents.train(mini_batch, train_steps)
                    train_steps += 1
            
            # 保存训练时的调度数据（每个epoch都保存，而不仅仅是评估时）
            if len(all_gantt_data) > 0:
                if self.n_agents is None:
                    self.n_agents = self.args.n_agents
                scheduleresults_path = get_data_file_path(
                    get_data_dir(), 
                    'scheduleresults.txt', 
                    self.n_agents, 
                    is_training=self.is_training
                )
                with open(scheduleresults_path, "a", encoding='utf-8') as f:
                    print(f"\n=== Epoch {epoch} ===", file=f)
                    for idx, gantt_data in enumerate(all_gantt_data):
                        print(f"Episode {idx}:", file=f)
                        print(gantt_data, file=f)

        # self.plt(num)

    def evaluate(self):
        win_number = 0
        episode_rewards = 0
        for epoch in range(self.args.evaluate_epoch):
            _, episode_reward, win_tag, for_gant, _ = self.rolloutWorker.generate_episode(epoch, evaluate=True)
            episode_rewards += episode_reward
            if win_tag:
                win_number += 1
        # 返回的是平均获胜次数和平均奖励
        # 注释掉for_gant的打印，避免输出过多数据
        # print(for_gant)
        return win_number / self.args.evaluate_epoch, episode_rewards / self.args.evaluate_epoch

    def plt(self, num):
        plt.figure()
        plt.axis([0, self.args.n_epoch, 0, 100])
        plt.cla()
        plt.subplot(2, 1, 1)
        plt.plot(range(len(self.win_rates)), self.win_rates)
        plt.xlabel('epoch*{}'.format(self.args.evaluate_cycle))
        plt.ylabel('win_rate')

        plt.subplot(2, 1, 2)
        plt.plot(range(len(self.episode_rewards)), self.episode_rewards)
        plt.xlabel('epoch*{}'.format(self.args.evaluate_cycle))
        plt.ylabel('episode_rewards')

        plt.savefig(self.save_path + '/plt_{}.png'.format(num), format='png')
        np.save(self.save_path + '/win_rates_{}'.format(num), self.win_rates)
        np.save(self.save_path + '/episode_rewards_{}'.format(num), self.episode_rewards)

    def select_actions(self, obs_list, avail_action, epsilon=0.0, evaluate=False):
        """
        兼容接口：根据当前观测和可用动作返回每个智能体的动作列表。
        obs_list: list-like of per-agent observations (len == n_agents) or a single observation repeated.
        avail_action: per-agent availability list or single availability for all agents.
        """
        actions = []
        # prepare last_action zeros
        last_action = np.zeros((self.args.n_agents, self.args.n_actions))
        # Normalize inputs to lists
        if not isinstance(obs_list, (list, tuple, np.ndarray)):
            obs_list = [obs_list] * self.args.n_agents
        if isinstance(obs_list, np.ndarray) and obs_list.shape[0] == self.args.n_agents:
            obs_iter = [obs_list[i] for i in range(self.args.n_agents)]
        else:
            obs_iter = list(obs_list)
        # avail_action could be per-agent list-of-lists or a single list
        if isinstance(avail_action, list) and len(avail_action) == self.args.n_agents and isinstance(avail_action[0], (list, tuple, np.ndarray)):
            avail_iter = avail_action
        else:
            avail_iter = [avail_action for _ in range(self.args.n_agents)]

        # ensure policy hidden state is initialized (some policies require it)
        try:
            if hasattr(self.rolloutWorker.agents.policy, 'init_hidden'):
                # episode_num = 1 for ad-hoc selection
                self.rolloutWorker.agents.policy.init_hidden(1)
        except Exception:
            pass

        for agent_id in range(self.args.n_agents):
            obs = obs_iter[agent_id] if agent_id < len(obs_iter) else obs_iter[0]
            avail = avail_iter[agent_id]
            # ensure avail length matches expected n_actions
            try:
                import numpy as _np
                avail_arr = _np.array(avail, dtype=float)
                if avail_arr.ndim == 0:
                    avail_arr = _np.array([float(avail_arr)])
                if avail_arr.shape[0] < self.args.n_actions:
                    pad = _np.zeros(self.args.n_actions - avail_arr.shape[0], dtype=float)
                    avail_arr = _np.concatenate([avail_arr, pad])
                elif avail_arr.shape[0] > self.args.n_actions:
                    avail_arr = avail_arr[: self.args.n_actions]
                avail = avail_arr.tolist()
            except Exception:
                # fallback: leave avail unchanged
                pass
            # call underlying agents.choose_action
            act = self.rolloutWorker.agents.choose_action(obs, last_action[agent_id], agent_id, avail, epsilon, evaluate)
            try:
                actions.append(int(act))
            except Exception:
                # act may be tensor
                try:
                    actions.append(int(act.cpu().numpy()))
                except Exception:
                    actions.append(int(act))
        return actions
