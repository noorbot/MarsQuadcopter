#! /usr/bin/env python3
import rospy
import open3d as o3d
import open3d_conversions
from sensor_msgs.msg import PointCloud2
import time
import numpy as np
import tf
#import ros_numpy
from scipy.spatial.transform import Rotation as R
import copy
import pandas as pd
import matplotlib.pyplot as plt
import sys
import csv

from visualization_msgs.msg import Marker
np.set_printoptions(threshold=sys.maxsize)


rospy.init_node('my_plane_segmentation')

current_cloud = None

master_obstacle_library = pd.DataFrame(columns = ['obst_num', 'center_x', 'center_y'])

# write data to csv               COMMENT BACK IN IF YOU WANT
# file = 'src/camera/experiment_data/Jan16_exp_centers.csv'
# trial_num = 4
# with open(file, 'a') as f: #prints header in csv
#                 write = csv.writer(f)
#                 label = [trial_num]
#                 write.writerow([])
#                 write.writerow([])
#                 write.writerow([])
#                 write.writerow(label)
#                 write.writerow(['label', 'x', 'y', 'z'])

# my function to create the transformation matrix from /map to /camera_depth_optical_frame
def convert_to_transfromation_matrix(trans, rot):
    r = R.from_quat(rot)        # convert quaternion to rotation matrix
    T = np.eye(4)               # initialize transformation matrix T
    T[0:3,0:3] = r.as_matrix()  # set rotation matrix elements
    T[0:3,3] = trans            # set translation vector elements
    return T

# my function to ignore the pointcloud points in the location of the turtlebots
def ignore_ttb_points(points_global):
    # ignore points around ttb location (20cm radius)
    # lets say we have a ttb at ttb_x, ttb_y
    ttb1_x = trans_ttb1[0]
    ttb1_y = trans_ttb1[1]
    center1 = np.array([ttb1_x, ttb1_y, 0.1])
    radius1 = 0.25
    distances1 = np.linalg.norm(points_global - center1, axis=1)
    points_global = points_global[distances1 >= radius1]
    cloud_global.points = o3d.utility.Vector3dVector(points_global) # ahjkh this line is causing issues.... can't display this pcd

    ttb2_x = trans_ttb2[0]
    ttb2_y = trans_ttb2[1]
    center2 = np.array([ttb2_x, ttb2_y, 0.1])
    radius2 = 0.25
    distances2 = np.linalg.norm(points_global - center2, axis=1)
    points_global = points_global[distances2 >= radius2]
    cloud_global.points = o3d.utility.Vector3dVector(points_global) # ahjkh this line is causing issues.... can't display this pcd

    return cloud_global


# my function to clean up the obstacle cloud and remove turtlebot points to leave only useful points
def clean_pointcloud_and_ttbs(outlier_cloud):
    # DBSAN CLUSTERING

    points_to_remove = []

    labels = np.array(outlier_cloud.cluster_dbscan(eps=0.03, min_points=10, print_progress=False))
    if len(np.unique(labels)) > -1:  # if robot is on floor the camera will detect zero clusters and the below code should not be executed
        max_label = labels.max()
        print(f"point cloud has {max_label + 1} clusters")
        colors = plt.get_cmap("tab20")(labels / (max_label if max_label > 0 else 1))
        colors[labels < 0] = 0
        outlier_cloud.colors = o3d.utility.Vector3dVector(colors[:, :3])

        # create pandas Dataframe with all outlier_cloud points including their DBSCAN clustering labels
        outlier_cloud_labels = pd.DataFrame(outlier_cloud.points, columns=['x','y', 'z'])
        outlier_cloud_labels['label'] = labels
        # remove all points with label -1 (noise)
        index_1 = outlier_cloud_labels[outlier_cloud_labels['label']==-1]
        points_to_remove = index_1.index.to_list() # list to store the index of all points which are to be removed
        # remove points with fewer than 50 members in the cluster, or only have members within the 'sandwich'

        for cluster in range(max_label+1):
            curr_label = outlier_cloud_labels[outlier_cloud_labels['label']==cluster]
            if(len(curr_label) < 50): # remove points that are in a cluster with fewer than 100 members 
                print("Removing small clusters from obstacle pointcloud")
                #points_to_remove.extend(curr_label.index.to_list())
            # if(not((abs(curr_label['z'].min()) > 0.03) or (abs(curr_label['z'].max()) > 0.03))): # remove points that are in a cluster with extreme z heights lower than 3cm from the ground.
            #     print("Removing shallow enclosed objects from obstacle pointcloud")
                #points_to_remove.extend(curr_label.index.to_list())

        # TTB1 removal
        if(trans_ttb1[2] !=100):  # only remove ttb if it is in sight (z is set to 100 when not in sight to move out of the way in tf_listener)
            print("removing TTB1 points from obstacle pointcloud")
            ttb1_x = trans_ttb1[0]
            ttb1_y = trans_ttb1[1]
            center1 = np.array([ttb1_x, ttb1_y, 0.15])
            pcd_tree = o3d.geometry.KDTreeFlann(outlier_cloud)  # build KDTree from outlier_cloud
            [k, idx, _] = pcd_tree.search_knn_vector_3d(center1, 1) # use knn to find 1 nearest point to ttb location
            ttb1_cluster_label = outlier_cloud_labels.at[idx[0], 'label'] # identify the label of this nearest point
            ttb1_cluster = outlier_cloud_labels[outlier_cloud_labels['label']==ttb1_cluster_label] # find all points with this label. this is the ttb cluster
            points_to_remove.extend(ttb1_cluster.index.to_list()) # update list to store the index of all points which are to be removed

        # TTB2 removal
        if(trans_ttb2[2] !=100):  # only remove ttb if it is in sight (z is set to 100 when not in sight to move out of the way in tf_listener)
            print("removing TTB2 points from obstacle pointcloud")
            ttb2_x = trans_ttb2[0]
            ttb2_y = trans_ttb2[1]
            center2 = np.array([ttb2_x, ttb2_y, 0.15])
            pcd_tree = o3d.geometry.KDTreeFlann(outlier_cloud)  # build KDTree from outlier_cloud
            [k, idx, _] = pcd_tree.search_knn_vector_3d(center2, 1) # use knn to find 1 nearest point to ttb location
            ttb2_cluster_label = outlier_cloud_labels.at[idx[0], 'label'] # identify the label of this nearest point
            ttb2_cluster = outlier_cloud_labels[outlier_cloud_labels['label']==ttb2_cluster_label] # find all points with this label. this is the ttb cluster
            points_to_remove.extend(ttb2_cluster.index.to_list()) # update list to store the index of all points which are to be removed
        
        outlier_cloud = outlier_cloud.select_by_index(points_to_remove, invert=True)
        print("outlier cloud size after cleaning: ")
        print(len(outlier_cloud.points))

        return outlier_cloud
    
def plane_segmentation(cloud_global):
    plane_model, inliers = cloud_global.segment_plane(distance_threshold=0.02,
                                             ransac_n=3,
                                             num_iterations=100)
    [a, b, c, d] = plane_model
    #print(f"Plane equation: {a:.2f}x + {b:.2f}y + {c:.2f}z + {d:.2f} = 0")
    #print("Displaying pointcloud with planar points in red ...")
    inlier_cloud = cloud_global.select_by_index(inliers)
    inlier_cloud.paint_uniform_color([0, 0, 0])
    outlier_cloud = cloud_global.select_by_index(inliers, invert=True)
    return outlier_cloud, inlier_cloud

def find_obstacle_positions(outlier_cloud):
    # DBSCAN Clustering
    labels = np.array(outlier_cloud.cluster_dbscan(eps=0.03, min_points=10, print_progress=False))
    max_label = labels.max()
    print(f"There are {max_label + 1} obstacles detected")
    # colors = plt.get_cmap("tab20")(labels / (max_label if max_label > 0 else 1))
    # colors[labels < 0] = 0
    # outlier_cloud.colors = o3d.utility.Vector3dVector(colors[:, :3])

    obstacle_library = pd.DataFrame(columns = ['center_x', 'center_y', 'top_z'])
    
    # create pandas Dataframe with all outlier_cloud points including their DBSCAN clustering labels
    outlier_cloud_labels = pd.DataFrame(outlier_cloud.points, columns=['x','y', 'z'])
    outlier_cloud_labels['label'] = labels
    
    # for each obstacle cluster, calculate its x and y centers and save it to the obstacle_library dataframe
    for cluster in range(max_label+1):
        curr_label = outlier_cloud_labels[outlier_cloud_labels['label']==cluster]
        center_x = curr_label['x'].mean()
        center_y = curr_label['y'].mean()
        top_z = curr_label['z'].max()
        obstacle_library.loc[cluster] = [center_x, center_y, top_z]
    
    print(obstacle_library)
    return(obstacle_library)


# CALLBACK FUNCTION TO READ POINTCLOUD DATA FROM SUBSCRIPTION
def handle_pointcloud(pointcloud2_msg):
    global current_cloud
    current_cloud = pointcloud2_msg

rate = rospy.Rate(10)

listener_pcd = rospy.Subscriber('/camera/depth/color/points', PointCloud2, handle_pointcloud, queue_size=1)
publisher1 = rospy.Publisher('inlier_cloud', PointCloud2, queue_size=1)
publisher2 = rospy.Publisher('outlier_cloud', PointCloud2, queue_size=1)
marker_pub = rospy.Publisher("/center_marker", Marker, queue_size = 2)

# create the TransformListener object
tf_listener_cam = tf.TransformListener()
tf_listener_ttb1 = tf.TransformListener()
tf_listener_ttb2 = tf.TransformListener()


while not rospy.is_shutdown():
    if current_cloud is None:
        continue

    try:
        # lookup transform between map and camera_depth_optical_frame
        (trans,rot) = tf_listener_cam.lookupTransform('/map', '/camera_depth_optical_frame', rospy.Time(0))
    except (tf.LookupException, tf.ConnectivityException, tf.ExtrapolationException):
        continue

    try: #HELLO I CHANGED THIS TO FIDUCIAL 3 JUST FOR TESTING!!!!
        # lookup transform between map and robot_1/base_footprint
        (trans_ttb1,rot_ttb1) = tf_listener_ttb1.lookupTransform('/map', '/fiducial_3', rospy.Time(0))
    except (tf.LookupException, tf.ConnectivityException, tf.ExtrapolationException):
        print("No tf data for robot_1. Set to z=100 for point removal(out of the way)")
        (trans_ttb1,rot_ttb1) = ([0.0, 0.0, 100.0], [0.0, 0.0, 0.0, 1.0])
        pass

    try:
        # lookup transform between map and robot_1/base_footprint
        (trans_ttb2,rot_ttb2) = tf_listener_ttb1.lookupTransform('/map', '/fiducial_1', rospy.Time(0))
    except (tf.LookupException, tf.ConnectivityException, tf.ExtrapolationException):
        print("No tf data for robot_2. Set to z=100 for point removal (out of the way)")
        (trans_ttb2,rot_ttb2) = ([0.0, 0.0, 100.0], [0.0, 0.0, 0.0, 1.0])
        pass


    # CONVERT POINTCLOUD MSG TO O3D DATATYPE
    o3d_cloud = open3d_conversions.from_msg(current_cloud)

    # VOXEL DOWNSAMPLING (FOR SPEED)
    o3d_cloud = o3d_cloud.voxel_down_sample(voxel_size=0.01)

    points = np.asarray(o3d_cloud.points)  # points are in the camera_depth_optical_frame

    # transform cloud to be global - apply transform from map to camera_depth_optical_frame
    T = convert_to_transfromation_matrix(trans, rot)  # convert the transform to a transformation matrix
    cloud_global = copy.deepcopy(o3d_cloud).transform(T)
    points_global = np.asarray(cloud_global.points)

    # ONLY CONSIDER POINTS THAT ARE UNDER 20 CM IN Z (BELOW TTB LIDAR)
    #cloud_global = cloud_global.select_by_index(np.where(points_global[:, 2] < 0.2)[0])
    
    # PLANE SEGMENTATION
    if(len(cloud_global.points)>100):
        outlier_cloud, inlier_cloud = plane_segmentation(cloud_global)

        # CHECK THAT WE HAVE AN OUTLIER_CLOUD FROM PLANE SEGMENTATION
        if(len(outlier_cloud.points)>100):
            # CALL FUNCTION TO CLEAN UP OBSTACLE POINTCLOUD and REMOVE TTB POINTS
            outlier_cloud = clean_pointcloud_and_ttbs(outlier_cloud)
            print(outlier_cloud)

            if(outlier_cloud is not None and len(outlier_cloud.points)>50):  # check if there are any obstacles, if yes proceed

                #obstacle_library = pd.Dataframe(columns = ['obstacle_num', 'center_x', 'center_y'])
                # obstacle_library = find_obstacle_positions(outlier_cloud)
        
                # center_marker = Marker()
                # center_marker.header.frame_id = "map"
                # center_marker.header.stamp = rospy.Time.now()
                # center_marker.type = 2
                # center_marker.id = 0
                # center_marker.scale.x = 0.03
                # center_marker.scale.y = 0.03
                # center_marker.scale.z = 0.03
                # center_marker.color.r = 1.0
                # center_marker.color.a = 1.0
                # center_marker.pose.position.x = obstacle_library.at[0, 'center_x']
                # center_marker.pose.position.y = obstacle_library.at[0, 'center_y']
                # center_marker.pose.position.z = obstacle_library.at[0, 'top_z']
                # center_marker.pose.orientation.x = 0.0
                # center_marker.pose.orientation.y = 0.0
                # center_marker.pose.orientation.z = 0.0
                # center_marker.pose.orientation.w = 1.0


                # obstacle_library.to_csv(file, mode='a', header=False)   #  COMMENT BACK IN IF WANTED
                

                # transform clouds back for visualization purposes
                outlier_cloud_vis = copy.deepcopy(outlier_cloud)
                outlier_cloud_vis.transform(np.linalg.inv(T))
                inlier_cloud_vis = copy.deepcopy(inlier_cloud)
                inlier_cloud_vis.transform(np.linalg.inv(T))

                # CONVERT O3D DATA BACK TO POINTCLOUD MSG TYPE - SEE TIME THIS TAKES (MOST TIME CONSUMING)
                ros_inlier_cloud = open3d_conversions.to_msg(inlier_cloud_vis, frame_id=current_cloud.header.frame_id, stamp=current_cloud.header.stamp)
                ros_outlier_cloud = open3d_conversions.to_msg(outlier_cloud_vis, frame_id=current_cloud.header.frame_id, stamp=current_cloud.header.stamp)

            
                publisher1.publish(ros_inlier_cloud)
                publisher2.publish(ros_outlier_cloud)
                # marker_pub.publish(center_marker)

    print("-------------------------")
    current_cloud = None
    rate.sleep()
