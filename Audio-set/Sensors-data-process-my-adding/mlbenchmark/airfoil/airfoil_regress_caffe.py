from pylab import *
import sys
import caffe
import os
import shutil
from sklearn.model_selection import train_test_split
import numpy as np
import pandas as pd
import time
import h5py
import tempfile
from caffe import layers as cl, params as P
from caffe.proto import caffe_pb2

def solver(train_net_path, test_net_path):
    s = caffe_pb2.SolverParameter()

    # Specify locations of the train and test networks.
    s.train_net = train_net_path
    s.test_net.append(test_net_path)

    s.test_interval = 100  # Test after every 1000 training iterations.
    s.test_iter.append(128) # Test 250 "batches" each time we test.

	# 500 Epochs --> (500 Epoch * 1503 # Samples)/(128 Batch Size) = Iterations
    s.max_iter = 58710      # # of times to update the net (training iterations)

    # Set the initial learning rate for stochastic gradient descent (SGD).
    s.base_lr = 0.001        

    # Set `lr_policy` to define how the learning rate changes during training.
    # Here, we 'step' the learning rate by multiplying it by a factor `gamma`
    # every `stepsize` iterations.
    s.lr_policy = 'step'
    s.gamma = 0.1
    s.stepsize = 5000

    # Set other optimization parameters. Setting a non-zero `momentum` takes a
    # weighted average of the current gradient and previous gradients to make
    # learning more stable. L2 weight decay regularizes learning, to help prevent
    # the model from overfitting.
    s.momentum = 0.9
    s.weight_decay = 5e-4

    # Display the current training loss and accuracy every 100 iterations.
    s.display = 100

    # Snapshots are files used to store networks we've trained.  Here, we'll
    # snapshot every 10K iterations -- just once at the end of training.
    # For larger networks that take longer to train, you may want to set
    # snapshot < max_iter to save the network and training state to disk during
    # optimization, preventing disaster in case of machine crashes, etc.
    s.snapshot = 10000
    s.snapshot_prefix = 'airfoil'

    # We'll train on the CPU for fair benchmarking against scikit-learn.
    # Changing to GPU should result in much faster training!
    s.type = 'Adam'
    #s.solver_mode = caffe_pb2.SolverParameter.CPU
    s.solver_mode = 0
	
    return s

# Encode a numeric column as zscores
def encode_numeric_zscore(df,name,mean=None,sd=None):
    if mean is None:
        mean = df[name].mean()

    if sd is None:
        sd = df[name].std()

    df[name] = (df[name]-mean)/sd
	
def to_xy(df,target):
    result = []
    for x in df.columns:
        if x != target:
            result.append(x)

    # find out the type of the target column.  Is it really this hard? :(
    target_type = df[target].dtypes
    target_type = target_type[0] if hasattr(target_type, '__iter__') else target_type
    
    # Encode to int for classification, float otherwise. TensorFlow likes 32 bits.
    if target_type in (np.int64, np.int32):
        # Classification
        return df.as_matrix(result).astype(np.float32),df.as_matrix([target]).astype(np.int32)
    else:
        # Regression
        return df.as_matrix(result).astype(np.float64),df.as_matrix([target]).astype(np.float64)

def get_model_dir(name,erase):
    base_path = os.path.join(".","saved_models")
    model_dir = os.path.join(base_path,name)
    os.makedirs(model_dir,exist_ok=True)
    if erase and len(model_dir)>4 and os.path.isdir(model_dir):
        shutil.rmtree(model_dir,ignore_errors=True) # be careful, this deletes everything below the specified path
    return model_dir


def mlp(inputfile, batch_size):
    # our version of LeNet: a series of linear and simple nonlinear transformations
    net = caffe.NetSpec()
    
    net.data, net.label = cl.HDF5Data(batch_size=batch_size, source=inputfile, ntop=2)
    net.fc1 = cl.InnerProduct(net.data, num_output=25, weight_filler=dict(type='xavier'))
    net.relu1 = cl.ReLU(net.fc1, in_place=True)
    net.fc2 = cl.InnerProduct(net.relu1, num_output=5, weight_filler=dict(type='xavier'))
    net.relu2 = cl.ReLU(net.fc2, in_place=True)
    net.fc3 = cl.InnerProduct(net.relu2, num_output=1, weight_filler=dict(type='xavier'))
    net.loss = cl.EuclideanLoss(net.fc3, net.label)

    return net.to_proto()
    

LEARNING_RATE = 0.001
BATCH_SIZE = 128;
path = "./data/"

filename_read = os.path.join(path,"airfoil_self_noise.csv")
df = pd.read_csv(filename_read,skiprows=1,na_values=['NA','?'])

encode_numeric_zscore(df,'Freq_Hz')
encode_numeric_zscore(df,'AoA_Deg')
encode_numeric_zscore(df,'Chord_m')
encode_numeric_zscore(df,'V_inf_mps')
encode_numeric_zscore(df,'displ_thick_m')

x_out,y_out = to_xy(df,'sound_db')

X_train, X_test, y_train, y_test = train_test_split(
    x_out, y_out, test_size=0.20, random_state=42)

# Write out the data to HDF5 files in a temp directory.
# This file is assumed to be caffe_root/examples/hdf5_classification.ipynb
dirname = os.path.abspath('./airfoil')
if not os.path.exists(dirname):
    os.makedirs(dirname)

train_filename = os.path.join(dirname, 'train.h5')
test_filename = os.path.join(dirname, 'test.h5')

f = h5py.File(train_filename, "w")
f.create_dataset("data", data=X_train,  compression="gzip", compression_opts=4)
f.create_dataset("label", data=y_train,  compression="gzip", compression_opts=4)
f.close()

with open(os.path.join(dirname, 'train.txt'), 'w') as f:
    f.write(train_filename + '\n')

f.close();

f = h5py.File(test_filename, "w")
f.create_dataset("data", data=X_test,  compression="gzip", compression_opts=4)
f.create_dataset("label", data=y_test,  compression="gzip", compression_opts=4)
f.close()

with open(os.path.join(dirname, 'test.txt'), 'w') as f:
    f.write(test_filename + '\n')
f.close();
	
train_net_path = 'airfoil/mlp_auto_train.prototxt'
with open(train_net_path, 'w') as f:
    f.write(str(mlp('airfoil/train.txt', BATCH_SIZE)))

f.close();
	
test_net_path = 'airfoil/mlp_auto_test.prototxt'
with open(test_net_path, 'w') as f:
    f.write(str(mlp('airfoil/test.txt', BATCH_SIZE)))

f.close();
	
solver_path = 'mlp_solver.prototxt'
with open(solver_path, 'w') as f:
    f.write(str(solver(train_net_path, test_net_path)))
	
f.close();
	
#caffe.set_device(0)
caffe.set_mode_cpu()
solver = caffe.get_solver(solver_path)
solver.solve()
