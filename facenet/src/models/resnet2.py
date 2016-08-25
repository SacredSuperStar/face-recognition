# Copyright 2016 The TensorFlow Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================

"""ResNet model.

Related papers:
https://arxiv.org/pdf/1603.05027v2.pdf
https://arxiv.org/pdf/1512.03385v1.pdf
https://arxiv.org/pdf/1605.07146v1.pdf
"""
from collections import namedtuple

import numpy as np
import tensorflow as tf
import models.network as network


HParams = namedtuple('HParams',
                     'batch_size, num_classes, min_lrn_rate, lrn_rate, '
                     'num_residual_units, use_bottleneck, weight_decay_rate, '
                     'relu_leakiness, optimizer')

#pylint: disable=unused-argument
def inference(images, output_dims, keep_probability, phase_train=True, weight_decay=0.0):
    hps = HParams(batch_size=None,
                             num_classes=128,
                             min_lrn_rate=0.0001,
                             lrn_rate=0.1,
                             num_residual_units=5,
                             use_bottleneck=False,
                             weight_decay_rate=0.0002,
                             relu_leakiness=0.1,
                             optimizer='mom')
    model = ResNet(hps, images, None, phase_train)
    logits1, logits2 = model.build_model(output_dims)

    return logits1, logits2


class ResNet(object):
    """ResNet model."""
  
    def __init__(self, hps, images, labels, phase_train):
        """ResNet constructor.
    
        Args:
          hps: Hyperparameters.
          images: Batches of images. [batch_size, image_size, image_size, 3]
          labels: Batches of labels. [batch_size, num_classes]
          mode: One of 'train' and 'eval'.
        """
        self.hps = hps
        self._images = images
        self.labels = labels
        self.phase_train = phase_train
    
        self._extra_train_ops = []
        self.lrn_rate = None
        self.train_op = None
        self.global_step = None
        self.summaries = None
        self.cost = None
        

    def build_graph(self):
        """Build a whole graph for the model."""
        self.global_step = tf.Variable(0, name='global_step', trainable=False)
        self.build_model([0, 0])
        self.summaries = tf.merge_all_summaries()
    
    def _stride_arr(self, stride):
        """Map a stride scalar to the stride array for tf.nn.conv2d."""
        return [1, stride, stride, 1]
    
    def build_model(self, output_dims):
        """Build the core model within the graph."""
        with tf.variable_scope('init'):
            x = self._images
            x = self._conv('init_conv', x, 3, 3, 16, self._stride_arr(1))
      
        strides = [1, 2, 2]
        activate_before_residual = [True, False, False]
        if self.hps.use_bottleneck:
            res_func = self._bottleneck_residual
            filters = [16, 64, 128, 256]
        else:
            res_func = self._residual
            filters = [16, 16, 32, 64]
        # Uncomment the following codes to use w28-10 wide residual network.
        # It is more memory efficient than very deep residual network and has
        # comparably good performance.
        # https://arxiv.org/pdf/1605.07146v1.pdf
        # filters = [16, 160, 320, 640]
        # Update hps.num_residual_units to 9
      
        with tf.variable_scope('unit_1_0'):
            x = res_func(x, filters[0], filters[1], self._stride_arr(strides[0]),
                         activate_before_residual[0])
        for i in xrange(1, self.hps.num_residual_units):
            with tf.variable_scope('unit_1_%d' % i):
                x = res_func(x, filters[1], filters[1], self._stride_arr(1), False)
      
        with tf.variable_scope('unit_2_0'):
            x = res_func(x, filters[1], filters[2], self._stride_arr(strides[1]),
                         activate_before_residual[1])
        for i in xrange(1, self.hps.num_residual_units):
            with tf.variable_scope('unit_2_%d' % i):
                x = res_func(x, filters[2], filters[2], self._stride_arr(1), False)
      
        with tf.variable_scope('unit_3_0'):
            x = res_func(x, filters[2], filters[3], self._stride_arr(strides[2]),
                         activate_before_residual[2])
        for i in xrange(1, self.hps.num_residual_units):
            with tf.variable_scope('unit_3_%d' % i):
                x = res_func(x, filters[3], filters[3], self._stride_arr(1), False)
      
        with tf.variable_scope('unit_last'):
            #pylint: disable=no-member
            x = network.batch_norm(x, int(x.get_shape()[3]), self.phase_train, 'final_bn')
            #x = self._batch_norm('final_bn', x)
            x = self._relu(x, self.hps.relu_leakiness)
            x = self._global_avg_pool(x)
      
        with tf.variable_scope('logits1'):
            logits1 = self._fully_connected(x, output_dims[0])

        with tf.variable_scope('logits2'):
            logits2 = self._fully_connected(x, output_dims[1])
#      self.predictions = tf.nn.softmax(logits)

#     with tf.variable_scope('costs'):
#       xent = tf.nn.softmax_cross_entropy_with_logits(
#           logits, self.labels)
#       self.cost = tf.reduce_mean(xent, name='xent')
#       self.cost += self._decay()
# 
#       moving_avg = tf.train.ExponentialMovingAverage(
#           0.99, num_updates=self.global_step, name='moving_avg')
#       self._extra_train_ops.append(moving_avg.apply([self.cost]))
#       tf.scalar_summary('cost', moving_avg.average(self.cost))
        return logits1, logits2

    def _build_train_op(self):
        """Build training specific ops for the graph."""
        self.lrn_rate = tf.constant(self.hps.lrn_rate, tf.float32)
        tf.scalar_summary('learning rate', self.lrn_rate)
    
        trainable_variables = tf.trainable_variables()
        grads = tf.gradients(self.cost, trainable_variables)
    
        if self.hps.optimizer == 'sgd':
            optimizer = tf.train.GradientDescentOptimizer(self.lrn_rate)
        elif self.hps.optimizer == 'mom':
            optimizer = tf.train.MomentumOptimizer(self.lrn_rate, 0.9)
    
        apply_op = optimizer.apply_gradients(
            zip(grads, trainable_variables),
            global_step=self.global_step, name='train_step')
    
        train_ops = [apply_op] + self._extra_train_ops
        self.train_op = tf.group(*train_ops)

    def _residual(self, x, in_filter, out_filter, stride,
                  activate_before_residual=False):
        """Residual unit with 2 sub layers."""
        if activate_before_residual:
            with tf.variable_scope('shared_activation'):
                x = network.batch_norm(x, int(x.get_shape()[3]), self.phase_train, 'init_bn')
                #x = self._batch_norm('init_bn', x)
                x = self._relu(x, self.hps.relu_leakiness)
                orig_x = x
        else:
            with tf.variable_scope('residual_only_activation'):
                orig_x = x
                x = network.batch_norm(x, int(x.get_shape()[3]), self.phase_train, 'init_bn')
                #x = self._batch_norm('init_bn', x)
                x = self._relu(x, self.hps.relu_leakiness)
    
        with tf.variable_scope('sub1'):
            x = self._conv('conv1', x, 3, in_filter, out_filter, stride)
    
        with tf.variable_scope('sub2'):
            #pylint: disable=no-member
            x = network.batch_norm(x, int(x.get_shape()[3]), self.phase_train, 'bn2')
            #x = self._batch_norm('bn2', x)
            x = self._relu(x, self.hps.relu_leakiness)
            x = self._conv('conv2', x, 3, out_filter, out_filter, [1, 1, 1, 1])
    
        with tf.variable_scope('sub_add'):
            if in_filter != out_filter:
                orig_x = tf.nn.avg_pool(orig_x, stride, stride, 'VALID')
                orig_x = tf.pad(
                    orig_x, [[0, 0], [0, 0], [0, 0],
                             [(out_filter-in_filter)//2, (out_filter-in_filter)//2]])
            x += orig_x
    
        #pylint: disable=no-member
        tf.logging.info('image after unit %s', x.get_shape())
        return x

    def _bottleneck_residual(self, x, in_filter, out_filter, stride,
                             activate_before_residual=False):
        """Bottleneck resisual unit with 3 sub layers."""
        if activate_before_residual:
            with tf.variable_scope('common_bn_relu'):
                x = network.batch_norm(x, int(x.get_shape()[3]), self.phase_train, 'init_bn')
                #x = self._batch_norm('init_bn', x)
                x = self._relu(x, self.hps.relu_leakiness)
                orig_x = x
        else:
            with tf.variable_scope('residual_bn_relu'):
                orig_x = x
                x = network.batch_norm(x, int(x.get_shape()[3]), self.phase_train, 'init_bn')
                #x = self._batch_norm('init_bn', x)
                x = self._relu(x, self.hps.relu_leakiness)
    
        with tf.variable_scope('sub1'):
            x = self._conv('conv1', x, 1, in_filter, out_filter/4, stride)
    
        with tf.variable_scope('sub2'):
            #pylint: disable=no-member
            x = network.batch_norm(x, int(x.get_shape()[3]), self.phase_train, 'bn2')
            #x = self._batch_norm('bn2', x)
            x = self._relu(x, self.hps.relu_leakiness)
            x = self._conv('conv2', x, 3, out_filter/4, out_filter/4, [1, 1, 1, 1])
    
        with tf.variable_scope('sub3'):
            #pylint: disable=no-member
            x = network.batch_norm(x, int(x.get_shape()[3]), self.phase_train, 'bn3')
            #x = self._batch_norm('bn3', x)
            x = self._relu(x, self.hps.relu_leakiness)
            x = self._conv('conv3', x, 1, out_filter/4, out_filter, [1, 1, 1, 1])
    
        with tf.variable_scope('sub_add'):
            if in_filter != out_filter:
                orig_x = self._conv('project', orig_x, 1, in_filter, out_filter, stride)
            x += orig_x
    
        #pylint: disable=no-member
        tf.logging.info('image after unit %s', x.get_shape())
        return x

    def _conv(self, name, x, filter_size, in_filters, out_filters, strides):
        """Convolution."""
        with tf.variable_scope(name):
            n = filter_size * filter_size * out_filters
            l2_regularizer = lambda t: network.l2_loss(t, weight=self.hps.weight_decay_rate)
            kernel = tf.get_variable(
                'DW', [filter_size, filter_size, in_filters, out_filters],
                tf.float32, initializer=tf.random_normal_initializer(
                    stddev=np.sqrt(2.0/n)),
                regularizer=l2_regularizer)
            return tf.nn.conv2d(x, kernel, strides, padding='SAME')

    def _relu(self, x, leakiness=0.0):
        """Relu, with optional leaky support."""
        return tf.select(tf.less(x, 0.0), leakiness * x, x, name='leaky_relu')

    def _fully_connected(self, x, out_dim):
        """FullyConnected layer for final output."""
#    x = tf.reshape(x, [self.hps.batch_size, -1])
        l2_regularizer = lambda t: network.l2_loss(t, weight=self.hps.weight_decay_rate)
        w = tf.get_variable(
            'DW', [x.get_shape()[1], out_dim],
            initializer=tf.uniform_unit_scaling_initializer(factor=1.0),
            regularizer=l2_regularizer)
        b = tf.get_variable('biases', [out_dim],
                            initializer=tf.constant_initializer())
        return tf.nn.xw_plus_b(x, w, b)

    def _global_avg_pool(self, x):
        assert x.get_shape().ndims == 4
        return tf.reduce_mean(x, [1, 2])

