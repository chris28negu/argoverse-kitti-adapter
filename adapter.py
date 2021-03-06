# Adapter 
"""The code to translate Argoverse dataset to KITTI dataset format"""


# Argoverse-to-KITTI Adapter

# Author: Yiyang Zhou 
# Email: yiyang.zhou@berkeley.edu

# Modified for fixing 3D bounding boxes floating issue
# Editor: Bo Wang (bo.wang01@sjsu.edu)

print('\nLoading files...')

from pyquaternion import Quaternion
from scipy.spatial.transform import Rotation as R

import argoverse
from argoverse.data_loading.argoverse_tracking_loader import ArgoverseTrackingLoader
import os
#os.sys.path.remove('/opt/ros/kinetic/lib/python2.7/dist-packages/')
from shutil import copyfile
from argoverse.utils import calibration
import json
import numpy as np
from argoverse.utils.calibration import CameraConfig
from argoverse.utils.cv2_plotting_utils import draw_clipped_line_segment
from argoverse.utils.se3 import SE3
from argoverse.utils.transform import quat2rotmat
import math
from typing import Union
import numpy as np
import pyntcloud
import progressbar
from time import sleep

"""
Your original file directory is:
argodataset
└── argoverse-tracking <----------------------------root_dir
    └── train <-------------------------------------data_dir
        └── 0ef28d5c-ae34-370b-99e7-6709e1c4b929
        └── 00c561b9-2057-358d-82c6-5b06d76cebcf
        └── ...
    └── validation
        └──5c251c22-11b2-3278-835c-0cf3cdee3f44
        └──...
    └── test
        └──8a15674a-ae5c-38e2-bc4b-f4156d384072
        └──...

"""


####CONFIGURATION#################################################
# Root directory
root_dir= '../../Datasets/argo/'

# Maximum thresholding distance for labelled objects
# (Object beyond this distance will not be labelled)
max_d=100

# camera image size
IMAGE_WIDTH = 1920
IMAGE_HEIGHT = 1200

####################################################################
_PathLike = Union[str, "os.PathLike[str]"]
def load_ply(ply_fpath: _PathLike) -> np.ndarray:
    """Load a point cloud file from a filepath.
    Args:
        ply_fpath: Path to a PLY file
    Returns:
        arr: Array of shape (N, 3)
    """
    data = pyntcloud.PyntCloud.from_file(os.fspath(ply_fpath))
    x = np.array(data.points.x)[:, np.newaxis]
    y = np.array(data.points.y)[:, np.newaxis]
    z = np.array(data.points.z)[:, np.newaxis]

    return np.concatenate((x, y, z), axis=1)

# Setup the root directory
data_dir=  root_dir+'train/'
goal_dir= root_dir+'training/'
if not os.path.exists(goal_dir):
    os.mkdir(goal_dir)
    os.mkdir(goal_dir+'velodyne')
    os.mkdir(goal_dir+'image_2')
    os.mkdir(goal_dir+'calib')
    os.mkdir(goal_dir+'label_2')
    os.mkdir(goal_dir+'velodyne_reduced')

# Check the number of logs(one continuous trajectory)
argoverse_loader= ArgoverseTrackingLoader(data_dir)
print('\nTotal number of logs:',len(argoverse_loader))
argoverse_loader.print_all()
print('\n')

cams=['ring_front_center',
 'ring_front_left',
 'ring_front_right',
 'ring_rear_left',
 'ring_rear_right',
 'ring_side_left',
 'ring_side_right']

# count total number of files
total_number=0
for q in argoverse_loader.log_list:
	path, dirs, files = next(os.walk(data_dir+q+'/lidar'))
	total_number= total_number+len(files)

total_number= total_number*7

bar = progressbar.ProgressBar(maxval=total_number, \
    widgets=[progressbar.Bar('=', '[', ']'), ' ', progressbar.Percentage()])

print('Total number of files: {}. Translation starts...'.format(total_number))
print('Progress:')
bar.start()

i= 0

for log_id in argoverse_loader.log_list:
    argoverse_data= argoverse_loader.get(log_id)
    for cam in cams:
        # Recreate the calibration file content 
        calibration_data=calibration.load_calib(data_dir+log_id+'/vehicle_calibration_info.json')[cam]
        extrinsic= calibration_data.extrinsic
        ext_rot= R.from_matrix(extrinsic[0:3,0:3].T)
        trans=  -(extrinsic[0:3,3]).reshape(3,1)
        extrinsic_kitti= np.hstack((extrinsic[0:3,0:3],-trans))
        #print(extrinsic)
        L3='P2: '
        for j in calibration_data.K.reshape(1,12)[0]:
            L3= L3+ str(j)+ ' '
        L3=L3[:-1]

        L6= 'Tr_velo_to_cam: '
        for k in extrinsic_kitti.reshape(1,12)[0][0:12]:
            L6= L6+ str(k)+ ' '
        L6=L6[:-1]


        L1='P0: 0 0 0 0 0 0 0 0 0 0 0 0'
        L2='P1: 0 0 0 0 0 0 0 0 0 0 0 0'
        L4='P3: 0 0 0 0 0 0 0 0 0 0 0 0'
        L5='R0_rect: 1 0 0 0 1 0 0 0 1'
        L7='Tr_imu_to_velo: 0 0 0 0 0 0 0 0 0 0 0 0'

        file_content="""{}
{}
{}
{}
{}
{}
{}
     """.format(L1,L2,L3,L4,L5,L6,L7)
        l=0


        # Loop through the each lidar frame (10Hz) to copy and reconfigure all images, lidars, calibration files, and label files.  
        for timestamp in argoverse_data.lidar_timestamp_list:

            # Save lidar file into .bin format under the new directory 
            lidar_file_path= data_dir + log_id + '/lidar/PC_' + str(timestamp) + '.ply'
            target_lidar_file_path= goal_dir + 'velodyne/'+ str(i).zfill(6) + '.bin'

            lidar_data=load_ply(lidar_file_path)
            lidar_data_augmented=np.concatenate((lidar_data,np.zeros([lidar_data.shape[0],1])),axis=1)
            lidar_data_augmented=lidar_data_augmented.astype('float32')
            lidar_data_augmented.tofile(target_lidar_file_path)

            # Save the image file into .png format under the new directory 
            cam_file_path=argoverse_data.image_list_sync[cam][l]
            target_cam_file_path= goal_dir +'image_2/' + str(i).zfill(6) + '.png'
            copyfile(cam_file_path,target_cam_file_path)

            file=open(goal_dir+'calib/' + str(i).zfill(6) + '.txt','w+')
            file.write(file_content)
            file.close()

            label_object_list= argoverse_data.get_label_object(l)
            file=open(goal_dir +  'label_2/' + str(i).zfill(6) + '.txt','w+')
            l+=1

            for detected_object in label_object_list:
                quat= Quar = R.from_quat(detected_object.quaternion)
                classes= detected_object.label_class
                occulusion= round(detected_object.occlusion/25)
                height= detected_object.height
                length= detected_object.length
                width= detected_object.width
                truncated= 0

                center= detected_object.translation # in ego frame 

                corners_ego_frame=detected_object.as_3d_bbox() # all eight points in ego frame 
                corners_cam_frame= calibration_data.project_ego_to_cam(corners_ego_frame) # all eight points in the camera frame 
                image_corners= calibration_data.project_ego_to_image(corners_ego_frame)
                image_bbox= [min(image_corners[:,0]), min(image_corners[:,1]),max(image_corners[:,0]),max(image_corners[:,1])]
                # the four coordinates we need for KITTI
                image_bbox=[round(x) for x in image_bbox]      

                center_cam_frame= calibration_data.project_ego_to_cam(np.array([center]))

                # the center coordinates in cam frame we need for KITTI
                if 0<center_cam_frame[0][2]<max_d and 0<image_bbox[0]<IMAGE_WIDTH and 0<image_bbox[1]<IMAGE_HEIGHT and 0<image_bbox[2]<IMAGE_WIDTH and  0<image_bbox[3]<IMAGE_HEIGHT:

                    # for the orientation, we choose point 1 and point 5 for application 
                    p1= corners_cam_frame[1]
                    p5= corners_cam_frame[5]
                    dz=p1[2]-p5[2]
                    dx=p1[0]-p5[0]
                    # the orientation angle of the car

                    angle= ext_rot * quat
                    angle=angle.as_euler('zyx')[1]

                    angle = (angle + np.pi) % (2 * np.pi) - np.pi 
                    beta= math.atan2(center_cam_frame[0][2],center_cam_frame[0][0])
                    alpha= (angle-beta + np.pi) % (2 * np.pi) - np.pi 
                    line=classes+ ' {} {} {} {} {} {} {} {} {} {} {} {} {} {} \n'.format(round(truncated,2),occulusion,round(alpha,2),round(image_bbox[0],2),round(image_bbox[1],2),round(image_bbox[2],2),round(image_bbox[3],2),round(height,2), round(width,2),round(length,2), round(center_cam_frame[0][0],2),round(center_cam_frame[0][1]+0.5*height,2),round(center_cam_frame[0][2],2),round(angle,2))

                    file.write(line)
            file.close()
            i+= 1
            if i< total_number:
            	bar.update(i+1)
bar.finish()
print('Translation finished, processed {} files'.format(i))
