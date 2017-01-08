"""Calculate embeddings for a dataset and store in a .mat file.
"""
# MIT License
# 
# Copyright (c) 2016 David Sandberg
# 
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
# 
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
# 
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import tensorflow as tf
import numpy as np
import argparse
import facenet
import os
import sys
import time
import scipy.io as sio
import importlib
import math

def main(args):
    network = importlib.import_module(args.model_def, 'inference')
  
    model_dir = '/media/data/DeepLearning/models/facenet/20161231-150622'
    model = os.path.join(os.path.expanduser(model_dir),'model-20161231-150622.ckpt-80000')

  
    train_set = facenet.get_dataset(args.dataset_dir)
    #train_set = train_set[0:50]
  
    with tf.Graph().as_default():
      
        # Get a list of image paths and their labels
        image_list, label_list = facenet.get_image_paths_and_labels(train_set)
        nrof_images = len(image_list)
        image_indices = range(nrof_images)

        image_batch, label_batch = facenet.read_and_augument_data(image_list, image_indices, args.image_size, args.batch_size, None, 
            False, False, False, nrof_preprocess_threads=4, shuffle=False)
        prelogits, _ = network.inference(image_batch, 1.0, 
            phase_train=False, weight_decay=0.0, reuse=False)
        embeddings = tf.nn.l2_normalize(prelogits, 1, 1e-10, name='embeddings')
        saver = tf.train.Saver(tf.global_variables())
        
        with tf.Session() as sess:
            saver.restore(sess, model)
            tf.train.start_queue_runners(sess=sess)
                
            embedding_size = int(embeddings.get_shape()[1])
            nrof_batches = int(math.ceil(nrof_images / args.batch_size))
            nrof_classes = len(train_set)
            label_array = np.array(label_list)
            class_names = [cls.name for cls in train_set]
            nrof_examples_per_class = [ len(cls.image_paths) for cls in train_set ]
            class_variance = np.zeros((nrof_classes,))
            class_center = np.zeros((nrof_classes,embedding_size))
            distance_to_center = np.ones((len(label_list),))*np.NaN
            emb_array = np.zeros((0,embedding_size))
            idx_array = np.zeros((0,), dtype=np.int32)
            lab_array = np.zeros((0,), dtype=np.int32)
            index_arr = np.append(0, np.cumsum(nrof_examples_per_class))
            for i in range(nrof_batches):
                t = time.time()
                emb, idx = sess.run([embeddings, label_batch])
                emb_array = np.append(emb_array, emb, axis=0)
                idx_array = np.append(idx_array, idx, axis=0)
                lab_array = np.append(lab_array, label_array[idx], axis=0)
                for cls in set(lab_array):
                    cls_idx = np.where(lab_array==cls)[0]
                    if cls_idx.shape[0]==nrof_examples_per_class[cls]:
                        # We have calculated all the embeddings for this class
                        i2 = np.argsort(idx_array[cls_idx])
                        emb_class = emb_array[cls_idx,:]
                        emb_sort = emb_class[i2,:]
                        center = np.mean(emb_sort, axis=0)
                        diffs = emb_sort - center
                        dists_sqr = np.sum(np.square(diffs), axis=1)
                        class_variance[cls] = np.mean(dists_sqr)
                        class_center[cls,:] = center
                        distance_to_center[index_arr[cls]:index_arr[cls+1]] = np.sqrt(dists_sqr)
                        emb_array = np.delete(emb_array, cls_idx, axis=0)
                        idx_array = np.delete(idx_array, cls_idx, axis=0)
                        lab_array = np.delete(lab_array, cls_idx, axis=0)

                        
                print('Batch %d in %.3f seconds' % (i, time.time()-t))
                
#             qqq = sio.loadmat('/home/david/casia_embeddings_tmp2.mat')
#             z2 = np.sum(nrof_examples_per_class[:cls])
#             w1 = np.where(np.abs(qqq['class_center'][:cls] - class_center[:cls])>1e-6)
#             w2 = np.where(np.abs(qqq['class_variance'][0,:cls] - class_variance[:cls])>1e-6)
#             w3 = np.where(np.abs(qqq['distance_to_center'][0,:z2] - distance_to_center[:z2])>1e-6)
            
            mdict = {'class_names':class_names, 'image_list':image_list, 'label_list':label_list, 'class_variance':class_variance, 
                  'class_center':class_center, 'distance_to_center':distance_to_center }
            sio.savemat(args.mat_file_name, mdict)
            
def parse_arguments(argv):
    parser = argparse.ArgumentParser()
    
    parser.add_argument('dataset_dir', type=str,
        help='Path to the directory containing aligned dataset.')
    parser.add_argument('model_def', type=str,
        help='Model definition. Points to a module containing the definition of the inference graph.')
    parser.add_argument('mat_file_name', type=str,
        help='The name of the mat file to store the embeddings in.')
    parser.add_argument('--image_size', type=int,
        help='Image size.', default=160)
    parser.add_argument('--batch_size', type=int,
        help='Number of images to process in a batch.', default=90)
    return parser.parse_args(argv)

if __name__ == '__main__':
    main(parse_arguments(sys.argv[1:]))
