import tensorflow as tf
import numpy as np
import util
import config
from model import *
from dataset import *

model = DCGAN(config.nz, config.nsf, config.nvx, config.batch_size, config.learning_rate)
dataset_i, dataset_o  = Dataset(config.dataset_path_i, config.dataset_path_o)
total_batch = dataset.num_examples / config.batch_size

for epoch in xrange(1, 51):
    for batch in xrange(total_batch):
        z = np.random.uniform(-1, 1, [config.batch_size, config.nz]).astype(np.float32)
        x = np.array(dataset_i.next_batch(config.batch_size))
        t = np.array(dataset_o.next_batch(config.batch_size))
        # z = np.split(z, 2) # multi-GPU mode
        # x = np.split(x, 2) # multi-GPU mode
        model.optimize(z, x, t)

        if batch % 100 == 0:
            lossC, lossD, lossG = model.get_errors(z, x, t)
            x_g = model.generate(z, x)
            for i, x in enumerate(x_g[:5]):
                util.save_binvox("./out/{0}-{1}.binvox".format(epoch, i), x > 0.5)
            print "{0:>2}, {1:>5}, {2:.8f}, {3:.8f}, {4:.8f}".format(epoch, batch, lossC, lossD, lossG)

    if epoch % 10 == 0:
        model.save("./params/epoch-{0}.ckpt".format(epoch))

model.close()
