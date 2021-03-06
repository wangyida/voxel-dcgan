import tensorflow as tf
import util
from ops import *
from vb import variational_bayes

class Model(object):

    def __init__(self, vars):
        self.saver = tf.train.Saver(vars)

    def session(self, sess):
        if sess is not None:
            self.sess = sess
        else:
            config_proto = tf.ConfigProto()
            config_proto.gpu_options.allow_growth = True
            self.sess = tf.Session(config=config_proto)

    def initialize(self):
        self.sess.run(tf.global_variables_initializer())

    def save(self, path):
        self.saver.save(self.sess, path)

    def restore(self, path):
        self.saver.restore(self.sess, path)

    def close(self):
        self.sess.close()

class DCGAN(Model):

    def __init__(self, nz, nsf, nvx, batch_size, learning_rate, sess=None):
        self.session(sess)
        opt = tf.train.AdamOptimizer(learning_rate, 0.5)
        tower_gradsC = []
        tower_gradsG = []
        tower_gradsD = []
        self.lossesC = []
        self.lossesG = []
        self.lossesD = []
        self.x_g_list = []
        self.train = tf.placeholder(tf.bool)
        self.netC = Coder()
        self.netG = Generator()
        self.netD = Discriminator()

        self.build_model(nz, nsf, nvx, batch_size, 0)
        gradsC = opt.compute_gradients(self.lossesC[-1], var_list=self.varsC)
        gradsG = opt.compute_gradients(self.lossesG[-1], var_list=self.varsG)
        gradsD = opt.compute_gradients(self.lossesD[-1], var_list=self.varsD)
        tower_gradsC.append(gradsC)
        tower_gradsG.append(gradsG)
        tower_gradsD.append(gradsD)

        # multi-GPU mode
        # gpus = ['/gpu:0', '/gpu:1']
        # n_gpu = len(gpus)
        # for i, gpu in enumerate(gpus):
        #     with tf.device(gpu):
        #         self.build_model(nz, nsf, nvx, batch_size/n_gpu, i)
        #         gradsG = opt.compute_gradients(self.lossesG[-1], var_list=self.varsG)
        #         gradsD = opt.compute_gradients(self.lossesD[-1], var_list=self.varsD)
        #         tower_gradsG.append(gradsG)
        #         tower_gradsD.append(gradsD)

        self.optC = opt.apply_gradients(average_gradients(tower_gradsC))
        self.optG = opt.apply_gradients(average_gradients(tower_gradsG))
        self.optD = opt.apply_gradients(average_gradients(tower_gradsD))
        self.lossC = tf.reduce_mean(self.lossesC)
        self.lossG = tf.reduce_mean(self.lossesG)
        self.lossD = tf.reduce_mean(self.lossesD)
        self.x_g = tf.concat(self.x_g_list, 0)

        if sess is None:
            self.initialize()

        variables_to_save = self.varsC + self.varsG + self.varsD + tf.moving_average_variables()
        super(DCGAN, self).__init__(variables_to_save)

    def build_model(self, nz, nsf, nvx, batch_size, gpu_idx):
        reuse = False if gpu_idx == 0 else True
        z = tf.placeholder(tf.float32, [batch_size, nz], 'z'+str(gpu_idx))
        x = tf.placeholder(tf.float32, [batch_size, nvx, nvx, nvx, 1], 'x'+str(gpu_idx))
        t = tf.placeholder(tf.float32, [batch_size, nvx, nvx, nvx, 1], 't'+str(gpu_idx))
        # x = tf.nn.max_pool3d(x, ksize=[1, 4, 4, 4, 1], strides=[1, 4, 4, 4, 1], padding='SAME')
        # t = tf.nn.max_pool3d(t, ksize=[1, 4, 4, 4, 1], strides=[1, 4, 4, 4, 1], padding='SAME')

        # coder 
        z, loss_z = self.netC(x, nz, self.train, nsf, nvx, reuse=reuse)

        # generator
        x_g = self.netG(z, self.train, nsf, nvx, reuse=reuse)
        self.x_g_list.append(x_g)

        # discriminator
        d_g = self.netD(x_g, self.train, nsf, nvx, reuse=reuse)
        d_r = self.netD(t, self.train, nsf, nvx, reuse=True)

        if gpu_idx == 0:
            t_vars = tf.trainable_variables()
            self.varsC = [var for var in t_vars if var.name.startswith('C')]
            self.varsG = [var for var in t_vars if var.name.startswith('G')]
            self.varsD = [var for var in t_vars if var.name.startswith('D')]

        # coding loss
        lossC_adv = tf.reduce_mean(loss_z)
        weight_decayC = tf.add_n([tf.nn.l2_loss(var) for var in self.varsC])
        self.lossesC.append(lossC_adv + 5e-4*weight_decayC)

        # generator loss
        lossG_adv = tf.reduce_mean(sigmoid_kl_with_logits(d_g, 0.8))
        weight_decayG = tf.add_n([tf.nn.l2_loss(var) for var in self.varsG])
        self.lossesG.append(lossG_adv + 5e-4*weight_decayG)

        # discriminator loss
        lossD_real = tf.reduce_mean(sigmoid_kl_with_logits(d_r, 0.8))
        lossD_fake = tf.reduce_mean(sigmoid_ce_with_logits(d_g, tf.zeros_like(d_g)))
        weight_decayD = tf.add_n([tf.nn.l2_loss(var) for var in self.varsD])
        self.lossesD.append(lossD_real + lossD_fake + 5e-4*weight_decayD)

    def optimize(self, z, x, t):
        fd = {'z0:0':z, 'x0:0':x, 't0:0':t, self.train:True}
        # fd = {'z0:0':z[0], 'z1:0':z[1], 'x0:0':x[0], 'x1:0':x[1], self.train:True} # multi-GPU mode
        self.sess.run(self.optC, feed_dict=fd)
        self.sess.run(self.optD, feed_dict=fd)
        self.sess.run(self.optG, feed_dict=fd)

    def get_errors(self, z, x, t):
        fd = {'z0:0':z, 'x0:0':x, 't0:0':t, self.train:False}
        # fd = {'z0:0':z[0], 'z1:0':z[1], 'x0:0':x[0], 'x1:0':x[1], self.train:False} # multi-GPU mode
        lossC = self.sess.run(self.lossC, feed_dict=fd)
        lossD = self.sess.run(self.lossD, feed_dict=fd)
        lossG = self.sess.run(self.lossG, feed_dict=fd)
        return lossC, lossD, lossG

    def generate(self, z, x):
        x_g = self.sess.run(self.x_g, feed_dict={'x0:0':x, 'z0:0':z, self.train:False})
        # x_g = self.sess.run(self.x_g, feed_dict={'z0:0':z[0], 'z1:0':z[1], self.train:False}) # multi-GPU mode
        return x_g[:, :, :, :, 0]

class DCGANTest(Model):

    def __init__(self, nz, nsf, nvx, batch_size, sess=None):
        self.session(sess)
        self.batch_size = batch_size
        self.nz = nz
        self.train = tf.placeholder(tf.bool)
        self.netG = Generator()
        self.build_model(nsf, nvx)

        if sess is None:
            self.initialize()

        variables_to_save = self.varsG + tf.moving_average_variables()
        super(DCGANTest, self).__init__(variables_to_save)

    def build_model(self, nsf, nvx):
        z = tf.placeholder(tf.float32, [self.batch_size, self.nz], 'z')
        self.x_g = self.netG(z, self.train, nsf, nvx)
        self.varsG = [var for var in tf.trainable_variables() if var.name.startswith('G')]

    def generate(self, z):
        x_g = self.sess.run(self.x_g, feed_dict={'z:0':z, self.train:False})
        return x_g[0, :, :, :, 0] > 0.9

class Coder(object):

    def __call__(self, x, nz, train, nsf, nvx, name="C", reuse=False):
        with tf.variable_scope(name, reuse=reuse):
            batch_size, _, _, _, _ = x.get_shape().as_list()
            nf = 32 # number of filters
            layer_idx = 1

            x *= binary_mask(x.get_shape())
            '''
            x = tf.cond(
                    train,
                    lambda: tf.multiply(
                        x, tf.cast(tf.random_uniform(shape=tf.shape(x), minval=0, maxval=1, dtype=tf.int32), tf.float32)),
                    lambda: x)
            '''
            u = conv3d(x, [3, 3, 3, 1, nf], 'h{0}'.format(layer_idx), bias=True, stride=1)
            h = lrelu(u)

            while nsf < nvx:
                layer_idx += 1
                u = conv3d(h, [4, 4, 4, nf, nf*2], 'h{0}'.format(layer_idx))
                h = lrelu(batch_norm(u, train, 'bn{0}'.format(layer_idx)))
                _, _, _, nvx, nf = h.get_shape().as_list()

            h = tf.reshape(h, [batch_size, -1])

            layer_idx += 1
            z, z_mu, z_log_sigma, loss_z = variational_bayes(
                h=h, n_code=nz)
            return z, loss_z 

class Generator(object):

    def __call__(self, z, train, nsf, nvx, name="G", reuse=False):
        with tf.variable_scope(name, reuse=reuse):
            batch_size, nz = z.get_shape().as_list()
            nf = 32 # number of filters
            layer_idx = 1

            u = linear(z, [nz, nsf*nsf*nsf*nf], 'h{0}'.format(layer_idx))
            h = tf.nn.relu(batch_norm(u, train, 'bn{0}'.format(layer_idx)))
            h = tf.reshape(h, [batch_size, nsf, nsf, nsf, nf])

            while nsf < nvx:
                layer_idx += 1
                u = deconv3d(h, [4, 4, 4, nf/2, nf], [batch_size, nsf*2, nsf*2, nsf*2, nf/2], 'h{0}'.format(layer_idx))
                h = tf.nn.relu(batch_norm(u, train, 'bn{0}'.format(layer_idx)))
                _, _, _, nsf, nf = h.get_shape().as_list()

            layer_idx += 1
            u = deconv3d(h, [3, 3, 3, 1, nf], [batch_size, nvx, nvx, nvx, 1], 'h{0}'.format(layer_idx), bias=True, stride=1)
            return tf.nn.sigmoid(u)

class Discriminator(object):

    def __call__(self, x, train, nsf, nvx, name="D", reuse=False):
        with tf.variable_scope(name, reuse=reuse):
            batch_size, _, _, _, _ = x.get_shape().as_list()
            nf = 32 # number of filters
            layer_idx = 1

            x *= binary_mask(x.get_shape())

            u = conv3d(x, [3, 3, 3, 1, nf], 'h{0}'.format(layer_idx), bias=True, stride=1)
            h = lrelu(u)

            while nsf < nvx:
                layer_idx += 1
                u = conv3d(h, [4, 4, 4, nf, nf*2], 'h{0}'.format(layer_idx))
                h = lrelu(batch_norm(u, train, 'bn{0}'.format(layer_idx)))
                _, _, _, nvx, nf = h.get_shape().as_list()

            h = tf.reshape(h, [batch_size, -1])
            h = minibatch_discrimination(h, 256, 32, 'md1')

            layer_idx += 1
            _, nf = h.get_shape().as_list()
            return linear(h, [nf, 1], 'h{0}'.format(layer_idx), bias=True)
