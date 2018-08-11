import sabre
import math
import numpy as np
import dual as a3c
import tensorflow as tf
import os
os.environ['CUDA_VISIBLE_DEVICES'] = '2'
#import tflearn

RAND_RANGE = 10000


class Zero(sabre.Abr):
    S_INFO = 10
    S_LEN = 10
    THROUGHPUT_NORM = 5 * 1024.0
    BITRATE_NORM = 8 * 1024.0
    TIME_NORM = 1000.0
   # A_DIM = len(VIDEO_BIT_RATE)
    ACTOR_LR_RATE = 1e-4
    CRITIC_LR_RATE = 1e-3
    A_DIM = 10
    GRADIENT_BATCH_SIZE = 32

    def __init__(self, scope):
        # self.gp = config['gp']
        # self.buffer_size = config['buffer_size']
        # self.abr_osc = config['abr_osc']
        # self.abr_basic = config['abr_basic']
        self.quality = 0
        #self.last_quality = 0
        self.state = np.zeros((Zero.S_INFO, Zero.S_LEN))
        self.quality_len = Zero.A_DIM
        gpu_options = tf.GPUOptions(allow_growth=True)
        self.sess = tf.Session(config=tf.ConfigProto(gpu_options=gpu_options))
        # with tf.Session() as sess, open(LOG_FILE + '_agent_' + str(agent_id), 'wb') as log_file:
        self.dual = a3c.DualNetwork(self.sess, scope)
        self.actor = a3c.ActorNetwork(self.sess,
                                      state_dim=[
                                          Zero.S_INFO, Zero.S_LEN], action_dim=self.quality_len,
                                      learning_rate=Zero.ACTOR_LR_RATE, scope=scope, dual=self.dual)
        self.critic = a3c.CriticNetwork(self.sess,
                                        state_dim=[Zero.S_INFO, Zero.S_LEN],
                                        learning_rate=Zero.CRITIC_LR_RATE, scope=scope, dual=self.dual)
        self.sess.run(tf.global_variables_initializer())
        self.history = []
        self.quality_history = []
        self.replay_buffer = []
        # self.s_batch = [np.zeros((Zero.S_INFO, Zero.S_LEN))]
        # action_vec = np.zeros(Zero.A_DIM)
        # self.a_batch = [action_vec]
        # self.r_batch = []
        # self.actor_gradient_batch = []
        # self.critic_gradient_batch = []

    def teach(self, buffer):
        for (s_batch, a_batch, r_batch) in buffer:
            _s = np.array(s_batch)
            _a = np.array(a_batch)
            #print(_s.shape, _a.shape)
            # for (_s, _a, _r) in zip(s_batch, a_batch, r_batch):
            #     _s = np.reshape(_s, (1, Zero.S_INFO, Zero.S_LEN))
            #     _a = np.reshape(_a, (1, Zero.A_DIM))
            #     if _r > 0:
            self.actor.teach(_s, _a)
            #self.replay_buffer.append((s, a, r))

    def clear(self):
        self.replay_buffer = []

    def learn(self, ratio=1.0):
        actor_gradient_batch, critic_gradient_batch = [], []

        for (s_batch, a_batch, r_batch) in self.replay_buffer:
            actor_gradient, critic_gradient, td_batch = \
                a3c.compute_gradients(s_batch=np.stack(s_batch),
                                      a_batch=np.vstack(a_batch),
                                      r_batch=np.vstack(r_batch),
                                      actor=self.actor, critic=self.critic,
                                      lr_ratio=ratio)

            actor_gradient_batch.append(actor_gradient)
            critic_gradient_batch.append(critic_gradient)
        #print('start learn')
        for i in range(len(actor_gradient_batch)):
            self.actor.apply_gradients(actor_gradient_batch[i])
            self.critic.apply_gradients(critic_gradient_batch[i])

        self.actor_gradient_batch = []
        self.critic_gradient_batch = []
        #self.replay_buffer = []

    def pull(self):
        # print(self.replay_buffer)
        _ret_buffer = []
        for (s_batch, a_batch, r_batch) in self.replay_buffer:
            if r_batch[-1] > 0:
                _ret_buffer.append((s_batch, a_batch, r_batch))
        return _ret_buffer

    def push(self, reward):
        # print(len(reward))
        s_batch, a_batch, r_batch = [], [], []
        _index = 0
        for (state, action) in self.history:
            s_batch.append(state)
            action_vec = np.zeros(Zero.A_DIM)
            action_vec[action] = 1
            a_batch.append(action_vec)
            r_batch.append(reward[_index])
            _index += 1
        #if win
        r_batch[-1] = reward[-1] * 10.0
        self.replay_buffer.append((s_batch, a_batch, r_batch))
        # actor_gradient, critic_gradient, td_batch = \
        #     a3c.compute_gradients(s_batch=np.stack(self.s_batch),
        #                           a_batch=np.vstack(self.a_batch),
        #                           r_batch=np.vstack(self.r_batch),
        #                           actor=self.actor, critic=self.critic)
        # td_loss = np.mean(td_batch)

        # self.actor_gradient_batch.append(actor_gradient)
        # self.critic_gradient_batch.append(critic_gradient)

        self.history = []
        self.quality_history = []
        self.state = np.zeros((Zero.S_INFO, Zero.S_LEN))

    def get_quality_delay(self, segment_index):
        #print(self.buffer_size, sabre.manifest.segment_time, sabre.get_buffer_level(),sabre.manifest.segments[segment_index])
        # print(sabre.log_history[-1],sabre.throughput)
        if segment_index != 0:
            self.quality_history.append(
                (sabre.played_bitrate, sabre.rebuffer_time, sabre.total_bitrate_change))
        if segment_index < 0:
            return
        manifest_len = len(sabre.manifest.segments)
        time, throughput, latency, quality, _ = sabre.log_history[-1]
        state = self.state
        state = np.roll(state, -1, axis=1)
        state[0, -1] = throughput / Zero.THROUGHPUT_NORM
        state[1, -1] = time / Zero.TIME_NORM
        state[2, -1] = latency / Zero.TIME_NORM
        state[3, -1] = quality / self.quality_len
        state[4, -1] = sabre.played_bitrate / Zero.BITRATE_NORM
        state[5, -1] = sabre.rebuffer_time / Zero.TIME_NORM
        state[6, -1] = (manifest_len - segment_index) / manifest_len
        state[7, 0:Zero.A_DIM] = np.array(sabre.manifest.bitrates /
                                          np.max(sabre.manifest.bitrates))
        _fft = np.fft.fft(state[0])
        state[8] = _fft.real
        state[9] = _fft.imag

        self.state = state
        action_prob = self.actor.predict(
            np.reshape(state, (1, Zero.S_INFO, Zero.S_LEN)))
        # print(action_prob[0])
        #quality = np.argmax(action_prob[0])
        action_cumsum = np.cumsum(action_prob[0])
        quality = (action_cumsum > np.random.randint(
            1, RAND_RANGE) / float(RAND_RANGE)).argmax()
        delay = 0
        self.history.append((self.state, quality))
        return (quality, delay)
