from runner import Runner
from environment import ScheduleEnv
from common.arguments import (
    get_common_args,
    get_coma_args,
    get_mixer_args,
    get_centralv_args,
    get_reinforce_args,
    get_commnet_args,
    get_g2anet_args,
)


if __name__ == '__main__':
    # 仅使用自定义调度环境，不再依赖 StarCraft2/SMAC
    # 如需更换智能体数量，可在此处修改 n_agents
    default_n_agents = 6

    for i in range(8):  # 保持原有循环结构（针对多算法），默认 alg=qmix 时只执行一次有意义
    args = get_common_args()

        # 环境初始化（默认 6 个智能体，可按需调整）
        env = ScheduleEnv(n_agents=default_n_agents)
        env.reset()
        env_info = env.get_env_info()
        args.n_actions = env_info["n_actions"]
        args.n_agents = env_info["n_agents"]
        args.state_shape = env_info["state_shape"]
        args.obs_shape = env_info["obs_shape"]
        args.episode_limit = env_info["episode_limit"]

        # 算法参数补全
    if args.alg.find('coma') > -1:  # 判断模型的参数
        args = get_coma_args(args)
    elif args.alg.find('central_v') > -1:
        args = get_centralv_args(args)
    elif args.alg.find('reinforce') > -1:
        args = get_reinforce_args(args)
    else:
        args = get_mixer_args(args)
    if args.alg.find('commnet') > -1:
        args = get_commnet_args(args)
    if args.alg.find('g2anet') > -1:
        args = get_g2anet_args(args)

    runner = Runner(env, args)
    if args.learn:
            runner.run(i)
    else:
            win_rate, _ = runner.evaluate()
            print('The win rate of {} is  {}'.format(args.alg, win_rate))
            break
        env.close()
