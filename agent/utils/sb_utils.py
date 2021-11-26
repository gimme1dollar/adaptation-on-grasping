import os
import time
import logging
import numpy as np


import model.SAC as sb
from agent.utils.policy_utils import AugmentedCnnPolicy as sacCnn

from stable_baselines3.common.vec_env import VecNormalize
from agent.utils.callback_utils import EvalCallback, SaveVecNormalizeCallback
from stable_baselines3.common.callbacks import BaseCallback, CheckpointCallback


class TensorboardCallback(BaseCallback):
    """
    Custom callback for plotting additional values in tensorboard.
    Success rate is integrated to Tensorboard
    """
    def __init__(self, task, tf, algo, log_freq, model_name, verbose=0):
        self.is_tb_set = False
        self.task = task
        self.algo = algo
        self.log_freq = log_freq
        self.old_timestep = -1
        self.model_name = model_name
        self.tf = tf != None
        super(TensorboardCallback, self).__init__(verbose)

    def _on_step(self) -> bool:
        # Log additional tensor
        history = self.task.get_attr("history")[0]
        rew = self.task.get_attr("episode_rewards")[0]
        sr = self.task.get_attr("sr_mean")[0]
        curr = self.task.get_attr("curriculum")[0]

        if self.num_timesteps is not self.old_timestep:            
            if self.num_timesteps % self.log_freq == 0:
                logging.info("model: {} Success Rate: {} Timestep Num: {} lambda: {}".format(self.model_name, sr, self.num_timesteps, curr._lambda))
            self.old_timestep = self.num_timesteps
        return True

class SBPolicy:
    def __init__(self, env, test_env, config, model_dir, 
                load_dir=None, algo='SAC', log_freq=1000):
        self.env = env
        self.test_env = test_env
        self.algo = algo
        self.config = config
        self.load_dir = load_dir
        self.model_dir = model_dir
        self.log_freq = log_freq
        self.norm = config['normalize']
 
    def learn(self):
        # Use deterministic actions for evaluation
        eval_path = self.model_dir + "/best_model"
        # TODO save checkpoints with vecnormalize callback pkl file
        save_vec_normalize = SaveVecNormalizeCallback(save_freq=1, save_path=eval_path)
        if self.norm:
            # Don't normalize the reward for test env
            self.test_env = VecNormalize(self.test_env, norm_obs=True, norm_reward=False, clip_obs=10.)
        eval_callback = EvalCallback(self.test_env, best_model_save_path=eval_path,
                                    log_path=eval_path+'/logs', eval_freq=200,
                                    n_eval_episodes=10, callback_on_new_best=save_vec_normalize,
                                    deterministic=False, render=False)
        checkpoint_callback = CheckpointCallback(save_freq=5000, save_path=self.model_dir+'/logs/', name_prefix='rl_model')
        #time_callback = TrainingTimeCallback()
        tensorboard_file = "tensorboard/"
        if self.algo == 'SAC':
            if not self.env.envs[0].is_simplified() and (self.env.envs[0].depth_obs or self.env.envs[0].full_obs):
                #policy_kwargs = {
                #    "layers": self.config[self.algo]['layers'],
                #    "cnn_extractor": custom_obs_policy.create_augmented_nature_cnn(1)}
                policy = sacCnn
            elif self.env.envs[0].depth_obs or self.env.envs[0].full_obs:
                #policy_kwargs = {}
                policy = sacCnn
            else:
                #policy_kwargs = {"layers": self.config[self.algo]['layers'], "layer_norm": False}
                #policy = sacMlp
                pass

            if self.load_dir:
                top_folder_idx = self.load_dir.rfind('/')
                top_folder_str = self.load_dir[0:top_folder_idx]
                if self.norm:
                    #self.env = VecNormalize(self.env, norm_obs=True, norm_reward=True, clip_obs=10.)
                    self.env = VecNormalize.load(os.path.join(top_folder_str, 'vecnormalize.pkl'), self.env)
                model = sb.SAC(policy,
                            self.env,
                            #policy_kwargs=policy_kwargs,
                            verbose=2,
                            gamma=self.config['discount_factor'],
                            buffer_size=self.config[self.algo]['buffer_size'],
                            batch_size=self.config[self.algo]['batch_size'],
                            learning_rate=self.config[self.algo]['step_size'],
                            tensorboard_log=tensorboard_file,
                            create_eval_env=False)
                model_load = sb.SAC.load(self.load_dir, self.env)
                params = model_load.get_parameters()
                model.set_parameters(params, exact_match=False)
            else:
                if self.norm:
                    self.env = VecNormalize(self.env, norm_obs=True, norm_reward=True,
                                            clip_obs=10.)
                model = sb.SAC(policy,
                            self.env,
                            #policy_kwargs=policy_kwargs,
                            verbose=2,
                            gamma=self.config['discount_factor'],
                            buffer_size=self.config[self.algo]['buffer_size'],
                            batch_size=self.config[self.algo]['batch_size'],
                            learning_rate=self.config[self.algo]['step_size'],
                            tensorboard_log=tensorboard_file,
                            create_eval_env=False)

        try:
            model.learn(total_timesteps=int(self.config[self.algo]['total_timesteps']), 
                        callback=[TensorboardCallback(self.env, tensorboard_file, self.algo, self.log_freq, self.model_dir),
                                   checkpoint_callback, 
                                   #eval_callback
                                   ])
        except KeyboardInterrupt:
            pass

        self.save(model, self.model_dir)
    
    def load_params(self, policy):
        top_folder_idx = self.load_dir.rfind('/')
        top_folder_str = self.load_dir[0:top_folder_idx]
        if self.norm:
            self.train_env = VecNormalize(self.train_env, training=True, norm_obs=False, norm_reward=False, clip_obs=10.)
            self.train_env = VecNormalize.load(os.path.join(top_folder_str, 'vecnormalize.pkl'), self.train_env)
            
        model = sb.SAC.load(self.load_dir, self.train_env)
        return model

    def save(self, model, model_dir):
        if '/' in model_dir:
            top_folder, model_name = model_dir.split('/')
        else:
            model_name = model_dir
        folder_path = model_dir + '/' + model_name

        if os.path.isfile(folder_path):
            print('File already exists \n')
            i = 1
            while os.path.isfile(folder_path + '.zip'):
                folder_path = '{}_{}'.format(folder_path, i)
                i += 1
            model.save(folder_path)
        else:
            print('Saving model to {}'.format(folder_path))
            model.save(folder_path)

        if self.norm:
            model.get_vec_normalize_env().save(os.path.join(model_dir, 'vecnormalize.pkl'))

