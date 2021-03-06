import numpy as np
import utils
import os
import argparse
from keras import backend as K
import iterator_dme
import sys
import pandas as pd

# arrange arguments
parser = argparse.ArgumentParser()
parser.add_argument(
    '--gpu_index',
    type=str,
    help="gpu index",
    required=True
    )
parser.add_argument(
    '--grade_type',
    type=str,
    required=True
    )
parser.add_argument(
    '--save_fig',
    type=bool,
    required=False
    )
FLAGS, _ = parser.parse_known_args()

# training settings 
batch_size = 4
os.environ['CUDA_VISIBLE_DEVICES'] = FLAGS.gpu_index

# set misc paths
fundus_dir = "../data/merged_training_set"
vessel_dir = "../data/merged_vessel"
grade_path = "../data/merged_labels.csv"
img_out_dir = "../outputs/check_segmentation_fovea"
train_img_check_dir = "../outputs/input_checks/check_segmentation_fovea/train"
val_img_check_dir = "../outputs/input_checks/check_segmentation_fovea/validation"
EX_segmentor_dir = "../model/EX_segmentor"
fovea_localizer_dir = "../model/fovea_localizer"
od_segmentor = "../model/od_segmentor"
if not os.path.isdir(img_out_dir):
    os.makedirs(img_out_dir)
if not os.path.isdir(train_img_check_dir):
    os.makedirs(train_img_check_dir)
if not os.path.isdir(val_img_check_dir):
    os.makedirs(val_img_check_dir)

# set iterator
training_set, validation_set = utils.split(fundus_dir, vessel_dir, grade_path, FLAGS.grade_type, 1)
val_batch_fetcher = iterator_dme.ValidationBatchFetcher(validation_set, batch_size, FLAGS.grade_type)

# create networks
K.set_learning_phase(False)
EX_segmentor = utils.load_network(EX_segmentor_dir)
fovea_localizer = utils.load_network(fovea_localizer_dir)
od_segmentor = utils.load_network(od_segmentor)

# start inference
check_train_batch, check_validation_batch = True, True
list_grades, list_od_found, list_sum_intensity_inside, list_sum_intensity_outside, list_fnames = [], [], [], [], []
for fnames, imgs_mean_subt, imgs_z, vessels, grades_onehot  in val_batch_fetcher():
    if check_validation_batch:
        utils.check_input(imgs_mean_subt, imgs_z, vessels, val_img_check_dir)
        check_validation_batch = False
    segmented = EX_segmentor.predict(imgs_mean_subt, batch_size=batch_size, verbose=0)
    fovea_loc, fovea_loc_vessel = fovea_localizer.predict([imgs_z, vessels], batch_size=batch_size, verbose=0)
    od_seg, od_seg_vessel = od_segmentor.predict([imgs_z, vessels], batch_size=batch_size, verbose=0)
    
    true_grades = np.argmax(grades_onehot, axis=1).tolist()
    od_found, sum_intensity_inside, sum_intensity_outside = utils.extract_features(segmented, od_seg, fovea_loc)

    list_fnames += [os.path.basename(fname).replace(".tif", "") for fname in fnames.tolist()]
    list_grades += true_grades
    list_od_found += od_found
    list_sum_intensity_inside += sum_intensity_inside
    list_sum_intensity_outside += sum_intensity_outside
    if FLAGS.save_fig:
        utils.save_figs_for_region_seg_check(segmented, od_seg, fovea_loc, true_grades, img_out_dir, fnames)

df = pd.DataFrame({'fname':list_fnames, 'od_found':list_od_found, 'sum_intensity_inside':list_sum_intensity_inside, 'sum_intensity_outside':list_sum_intensity_outside, 'grade':list_grades})
df.to_csv("../outputs/dme_features.csv", index=False)
sys.stdout.flush()
