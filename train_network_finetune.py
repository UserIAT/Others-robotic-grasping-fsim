import subprocess
import os
from datetime import datetime

now = datetime.now()
current_time = now.strftime('%Y-%m%d-%H%M')
import glob

dataset_name = 'Fsim'

if dataset_name == 'Fsim':
    scene_list = ['multi', 'single']
    modality_list = ['rgb-d', 'depth', 'rgb']
    train_cmd_base = 'python3 train_network.py --dataset=None --dataset-path=None --use-depth=None --use-rgb=None --split=None --ds-rotate=None\
                                             --description=None '
    test_cmd_base = 'python3 eval_ggcnn.py --dataset=None --dataset-path=None --use-depth=None --use-rgb=None --split=None --ds-rotate=None\
                                             --description=None '
    cmds = []
    for scene in scene_list:
        for modality in modality_list:
            for fold in range(5):
                version_name = os.path.join(current_time + '_' + scene, modality, scene + '_' + modality + '_Fold_' + str(fold))
                use_rgb = None
                use_depth = None
                if modality == 'rgb':
                    use_rgb = 1
                    use_depth = 0
                elif modality == 'depth':
                    use_rgb = 0
                    use_depth = 1
                elif modality == 'rgb-d':
                    use_rgb = 1
                    use_depth = 1
                dataset_dir = os.path.join(dataset_name.lower() + '_grasp_dataset_' + scene)
                replace_dict = {'--dataset=None':'--dataset=' + dataset_name.lower(),
                                '--description=None':'--description=' + version_name,
                                '--dataset-path=None':'--dataset-path=' + dataset_dir,
                                '--use-rgb=None':'--use-rgb=' + str(use_rgb),
                                '--use-depth=None':'--use-depth=' + str(use_depth),
                                '--split=None':'--split=0.8',
                                '--ds-rotate=None':'--ds-rotate=' + str(fold * 0.2)}
                train_cmd_current = train_cmd_base
                test_cmd_current = test_cmd_base

                for ori_args, now_args in replace_dict.items():
                    train_cmd_current = train_cmd_current.replace(ori_args, now_args)
                    test_cmd_current = test_cmd_current.replace(ori_args, now_args)

                cmds.extend([train_cmd_current])
                # cmds.extend([train_cmd_current, test_cmd_current])
                # cmds.extend([test_cmd_current])


for cmd in cmds:
    p = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE)
    for line in iter(p.stdout.readline, b''):
        msg = line.strip().decode('gbk')
        print(msg)