import argparse
import sys
import os
import random
import math
import time
import numpy as np
import cupy as xp
import chainer
import chainer.functions as cf
from chainer.backends import cuda

sys.path.append(os.path.join("..", "..", ".."))
import gqn

sys.path.append(os.path.join(".."))
from hyper_parameters import HyperParameters
from model import Model


def make_uint8(array):
    if (array.shape[2] == 3):
        return np.uint8(np.clip((to_cpu(array) + 1) * 0.5 * 255, 0, 255))
    return np.uint8(
        np.clip((to_cpu(array.transpose(1, 2, 0)) + 1) * 0.5 * 255, 0, 255))


def to_gpu(array):
    if args.gpu_device >= 0:
        return cuda.to_gpu(array)
    return array


def to_cpu(array):
    if args.gpu_device >= 0:
        return cuda.to_cpu(array)
    return array


def main():
    dataset = gqn.data.Dataset(args.dataset_path)
    sampler = gqn.data.Sampler(dataset)
    iterator = gqn.data.Iterator(sampler, batch_size=args.batch_size)

    hyperparams = HyperParameters()
    model = Model(hyperparams, hdf5_path=args.snapshot_path)
    model.to_gpu()

    figure = gqn.imgplot.figure()
    axes = []
    sqrt_batch_size = int(math.sqrt(args.batch_size))
    axis_size = 1.0 / sqrt_batch_size
    for y in range(sqrt_batch_size):
        for x in range(sqrt_batch_size * 2):
            axis = gqn.imgplot.image()
            axes.append(axis)
            figure.add(axis, axis_size / 2 * x, axis_size * y, axis_size / 2,
                       axis_size)
    window = gqn.imgplot.window(figure, (1600, 800), "Reconstucted images")
    window.show()

    with chainer.using_config("train", False), chainer.using_config(
            "enable_backprop", False):
        for subset_index, subset in enumerate(dataset):
            iterator = gqn.data.Iterator(subset, batch_size=args.batch_size)

            for data_indices in iterator:
                # shape: (batch, views, height, width, channels)
                # range: [-1, 1]
                images, viewpoints = subset[data_indices]

                image_size = images.shape[2:4]
                total_views = images.shape[1]

                # sample number of views
                num_views = random.choice(range(total_views))
                query_index = random.choice(range(total_views))

                if num_views > 0:
                    observed_images = images[:, :num_views]
                    observed_viewpoints = viewpoints[:, :num_views]

                    # (batch, views, height, width, channels) -> (batch * views, height, width, channels)
                    observed_images = observed_images.reshape(
                        (args.batch_size * num_views, ) +
                        observed_images.shape[2:])
                    observed_viewpoints = observed_viewpoints.reshape(
                        (args.batch_size * num_views, ) +
                        observed_viewpoints.shape[2:])

                    # (batch * views, height, width, channels) -> (batch * views, channels, height, width)
                    observed_images = observed_images.transpose((0, 3, 1, 2))

                    # transfer to gpu
                    observed_images = to_gpu(observed_images)
                    observed_viewpoints = to_gpu(observed_viewpoints)

                    r = model.representation_network.compute_r(
                        observed_images, observed_viewpoints)

                    # (batch * views, channels, height, width) -> (batch, views, channels, height, width)
                    r = r.reshape((args.batch_size, num_views) + r.shape[1:])

                    # sum element-wise across views
                    r = cf.sum(r, axis=1)
                else:
                    r = np.zeros(
                        (args.batch_size, hyperparams.channels_r) +
                        hyperparams.chrz_size,
                        dtype="float32")
                    r = to_gpu(r)

                query_images = images[:, query_index]
                query_viewpoints = viewpoints[:, query_index]

                # (batch * views, height, width, channels) -> (batch * views, channels, height, width)
                query_images = query_images.transpose((0, 3, 1, 2))

                # transfer to gpu
                query_images = to_gpu(query_images)
                query_viewpoints = to_gpu(query_viewpoints)

                reconstructed_images = model.reconstruct_image(
                    query_images, query_viewpoints, r, xp)

                if window.closed():
                    exit()

                for batch_index in range(args.batch_size):
                    axis = axes[batch_index * 2 + 0]
                    image = query_images[batch_index]
                    axis.update(make_uint8(image))

                    axis = axes[batch_index * 2 + 1]
                    image = reconstructed_images[batch_index]
                    axis.update(make_uint8(image))

                time.sleep(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-path", type=str, default="../rooms_dataset")
    parser.add_argument("--snapshot-path", type=str, default="../snapshot")
    parser.add_argument("--batch-size", "-b", type=int, default=16)
    parser.add_argument("--gpu-device", "-gpu", type=int, default=0)
    args = parser.parse_args()
    main()
