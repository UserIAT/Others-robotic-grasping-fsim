import argparse
import logging
import time

import numpy as np
import torch.utils.data
import os 

from inference.models import get_network
from hardware.device import get_device
from inference.post_process import post_process_output
from utils.data import get_dataset
from utils.dataset_processing import evaluation, grasp
from utils.visualisation.plot import save_results
from tqdm import tqdm

logging.basicConfig(level=logging.INFO)
root_folder = os.path.dirname(os.path.abspath(__file__))

def parse_args():
    parser = argparse.ArgumentParser(description='Evaluate networks')

    # Network
    # parser.add_argument('--network', metavar='N', type=str, nargs='+', default='2022-1103-1514_Jacquard/RGB/Fold_0/logs/epoch_40_iou_0.85',
    # parser.add_argument('--network', type=str, 
    #                     default=["prediction/2022-1028-0008_multi/depth/multi_depth_Fold_0/logs/epoch_45_iou_0.77"])
    # parser.add_argument('--network', type=str, 
    #                     default=[os.path.join(root_folder, f) for f in ["prediction/2022-1028-0008_multi/rgb/multi_rgb_Fold_0/logs/epoch_40_iou_0.67"]])
    parser.add_argument('--network', type=str, 
                        default=[os.path.join(root_folder, f) for f in ["prediction/2022-1103-1514_Jacquard/DEPTH/Fold_0/logs/epoch_43_iou_0.93"]])
    parser.add_argument('--network-name', type=str, default='grconvnet3',
                        help='Network name in inference/models')
    parser.add_argument('--input-size', type=int, default=420,
                        help='Input image size for the network')

    # Dataset
    parser.add_argument('--dataset', type=str, default='cornell',
                        help='Dataset Name ("cornell" or "jaquard")')
    parser.add_argument('--dataset-path', type=str, default= os.path.join(root_folder, 'cornell_grasp_dataset'),
                        help='Path to dataset')
    parser.add_argument('--use-depth', type=int, default=1,
                        help='Use Depth image for evaluation (1/0)')
    parser.add_argument('--use-rgb', type=int, default=0,
                        help='Use RGB image for evaluation (1/0)')
    parser.add_argument('--use-dropout', type=int, default=0,
                        help='Use dropout for training (1/0)')
    parser.add_argument('--dropout-prob', type=float, default=0.1,
                        help='Dropout prob for training (0-1)')
    parser.add_argument('--channel-size', type=int, default=32,
                        help='Internal channel size for the network')
    parser.add_argument('--augment', action='store_true',
                        help='Whether data augmentation should be applied')
    parser.add_argument('--split', type=float, default=0.8,
                        help='Fraction of data for training (remainder is validation)')
    parser.add_argument('--ds-shuffle', action='store_true', default=False,
                        help='Shuffle the dataset')
    parser.add_argument('--ds-rotate', type=float, default=0.0,
                        help='Shift the start point of the dataset to use a different test/train split')
    parser.add_argument('--num-workers', type=int, default=8,
                        help='Dataset workers')

    # Evaluation
    parser.add_argument('--n-grasps', type=int, default=1,
                        help='Number of grasps to consider per image')
    parser.add_argument('--iou-threshold', type=float, default=0.25,
                        help='Threshold for IOU matching')
    parser.add_argument('--iou-eval', type=bool, default=True, 
                        help='Compute success based on IoU metric.')
    parser.add_argument('--jacquard-output', type=bool, default=False, 
                        help='Jacquard-dataset style output')

    # Misc.
    parser.add_argument('--vis', type=bool, default=False,
                        help='Visualise the network output')
    parser.add_argument('--cpu', dest='force_cpu', action='store_true', default=False,
                        help='Force code to run in CPU mode')
    parser.add_argument('--random-seed', type=int, default=123,
                        help='Random seed for numpy')

    args = parser.parse_args()

    if args.jacquard_output and args.dataset != 'jacquard':
        raise ValueError('--jacquard-output can only be used with the --dataset jacquard option.')
    if args.jacquard_output and args.augment:
        raise ValueError('--jacquard-output can not be used with data augmentation.')

    return args


if __name__ == '__main__':
    args = parse_args()

    # Get the compute device
    device = get_device(args.force_cpu)

    # Load Dataset
    logging.info('Loading {} Dataset...'.format(args.dataset.title()))
    Dataset = get_dataset(args.dataset)
    test_dataset = Dataset(args.dataset_path,
                           output_size=args.input_size,
                           ds_rotate=args.ds_rotate,
                           random_rotate=args.augment,
                           random_zoom=args.augment,
                           include_depth=args.use_depth,
                           include_rgb=args.use_rgb)

    indices = list(range(test_dataset.length))
    split = int(np.floor(args.split * test_dataset.length))
    if args.ds_shuffle:
        np.random.seed(args.random_seed)
        np.random.shuffle(indices)
    val_indices = indices[split:]
    val_sampler = torch.utils.data.sampler.SubsetRandomSampler(val_indices)
    logging.info('Validation size: {}'.format(len(val_indices)))

    test_data = torch.utils.data.DataLoader(
        test_dataset,
        batch_size=1,
        num_workers=args.num_workers,
        sampler=val_sampler
    )
    logging.info('Done')

    for network in args.network:
        logging.info('\nEvaluating model {}'.format(network))

        # # Load Network
        net = torch.load(network)
        torch.save(net.state_dict(), network + '_statedict.pt' )
        net.eval()

        # Load the network
        logging.info('Loading Network...')
        input_channels = 1 * args.use_depth + 3 * args.use_rgb
        net_type = get_network(args.network_name)
        net = net_type(
            input_channels=input_channels,
            dropout=args.use_dropout,
            prob=args.dropout_prob,
            channel_size=args.channel_size
        )
        net = net.to(device)
        logging.info('Done')
        net.load_state_dict(torch.load(network + '_statedict.pt'))
        net.eval()

        results = {'correct': 0, 'failed': 0}

        if args.jacquard_output:
            jo_fn = network + '_jacquard_output.txt'
            with open(jo_fn, 'w') as f:
                pass

        start_time = time.time()

        with torch.no_grad():
            pbar = tqdm(test_data)
            for idx, (x, y, didx, rot, zoom) in enumerate(pbar):
                xc = x.to(device)
                yc = [yi.to(device) for yi in y]
                lossd = net.compute_loss(xc, yc)

                q_img, ang_img, width_img = post_process_output(lossd['pred']['pos'], lossd['pred']['cos'],
                                                                lossd['pred']['sin'], lossd['pred']['width'])

                if args.iou_eval:
                    s = evaluation.calculate_iou_match(q_img, ang_img, test_data.dataset.get_gtbb(didx, rot, zoom),
                                                       no_grasps=args.n_grasps,
                                                       grasp_width=width_img,
                                                       threshold=args.iou_threshold
                                                       )
                    if s:
                        results['correct'] += 1
                    else:
                        results['failed'] += 1

                if args.jacquard_output:
                    grasps = grasp.detect_grasps(q_img, ang_img, width_img=width_img, no_grasps=1)
                    with open(jo_fn, 'a') as f:
                        for g in grasps:
                            f.write(test_data.dataset.get_jname(didx) + '\n')
                            f.write(g.to_jacquard(scale=1024 / 300) + '\n')

                if args.vis:
                    save_results(
                        rgb_img=test_data.dataset.get_rgb(didx, rot, zoom, normalise=False),
                        depth_img=test_data.dataset.get_depth(didx, rot, zoom),
                        grasp_q_img=q_img,
                        grasp_angle_img=ang_img,
                        no_grasps=args.n_grasps,
                        grasp_width_img=width_img,
                        index = str(idx),
                    )

        avg_time = (time.time() - start_time) / len(test_data)
        logging.info('Average evaluation time per image: {}ms'.format(avg_time * 1000))

        if args.iou_eval:
            logging.info('IOU Results: %d/%d = %f' % (results['correct'],
                                                      results['correct'] + results['failed'],
                                                      results['correct'] / (results['correct'] + results['failed'])))

        if args.jacquard_output:
            logging.info('Jacquard output saved to {}'.format(jo_fn))

        del net
        torch.cuda.empty_cache()
