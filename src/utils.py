import pandas as pd
import seaborn as sns
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import folium
import random

import base64
from io import BytesIO
import time
from IPython.display import display, clear_output

import subprocess
from google.cloud import storage

import ee
ee.Initialize()


# Define a method for displaying Earth Engine image tiles to folium map.
def add_ee_layer(self, ee_image_object, vis_params, name):
    map_id_dict = ee.Image(ee_image_object).getMapId(vis_params)
    folium.raster_layers.TileLayer(
        tiles=map_id_dict['tile_fetcher'].url_format,
        attr="Map Data © OCI | Google Earth Engine",
        name=name,
        overlay=True,
        control=True
    ).add_to(self)

# Add Earth Engine drawing method to folium.
folium.Map.add_ee_layer = add_ee_layer


def style_function(feature):
    class_label = "Not Damaged" if feature['properties']['class_0'] > feature['properties']['class_1'] else "Damaged"
    return {'fillColor': 'green' if class_label == "Not Damaged" else 'red', 
            'color': 'green' if class_label == "Not Damaged" else 'red'}

def create_feature_group(prediction_geojson):
    damage_data = []
    feature_group = folium.FeatureGroup(name='Prediction Points')
    
    for feature in prediction_geojson['features']:
        class_label = "Not Damaged" if feature['properties']['class_0'] > feature['properties']['class_1'] else "Damaged"
        damage_data.append(class_label)

        # Create GeoJson object
        geojson = folium.GeoJson(feature, 
                                 style_function=style_function, 
                                 tooltip=f"Class: {class_label}").add_to(feature_group)

    return feature_group, damage_data


def create_building_type(prediction_geojson):
    color_dict = {}  # Dictionary to store building types and their colors
    color_palette = list(map(mcolors.rgb2hex, sns.color_palette('tab10')))  # Use Seaborn's 'tab10' color palette
    color_index = 0

    def get_random_color():
        r = lambda: random.randint(0,255)
        return '#%02X%02X%02X' % (r(),r(),r())

    def get_color():
        nonlocal color_index
        if color_index < len(color_palette):
            color = color_palette[color_index]
            color_index += 1
        else:
            color = get_random_color()
        return color

    feature_group = folium.FeatureGroup(name='Building Type')

    for feature in prediction_geojson['features']:
        building_type = feature['properties']['building']
        if building_type not in color_dict:
            color_dict[building_type] = get_color()

        # Create GeoJson object
        geojson = folium.GeoJson(feature, 
                                 style_function=lambda feature: {'fillColor': color_dict[feature['properties']['building']], 'color': color_dict[feature['properties']['building']]}, 
                                 tooltip=f"Building Type: {building_type}").add_to(feature_group)

    return feature_group


def add_pie_chart_marker(damage_data, building_data, aoi):
    # Create damage and building DataFrame
    df = pd.DataFrame({
        'Damage': damage_data,
        'Building Type': building_data
    })

    # Create a pie chart with matplotlib
    colors = sns.color_palette('tab20', n_colors=df['Building Type'].nunique()).as_hex()
    fig, ax = plt.subplots(1, 2, figsize=(8, 4))

    # Damage Pie Chart
    explode_damage = (0.1, 0)  # Explode 1st slice
    ax[0].pie(df['Damage'].value_counts(), labels=df['Damage'].value_counts().index,
              autopct='%1.1f%%', startangle=140, colors=['lightcoral', 'lightskyblue'], explode=explode_damage, shadow=True)
    ax[0].set_title("Distribution of Building Damage", fontsize=15)
    ax[0].axis('equal')  # Equal aspect ratio ensures that pie is drawn as a circle.

    # Building Type Pie Chart
    explode_building = (0.1,) * df['Building Type'].nunique()  # Explode all slices
    ax[1].pie(df['Building Type'].value_counts(), labels=df['Building Type'].value_counts().index,
              autopct='%1.1f%%', startangle=140, colors=colors, explode=explode_building, shadow=True)
    ax[1].set_title("Distribution of Building Types", fontsize=15)
    ax[1].axis('equal')  # Equal aspect ratio ensures that pie is drawn as a circle.

    plt.tight_layout()
    plt.close()

    # Convert plot to PNG image
    img = BytesIO()
    fig.savefig(img, format='png')
    img.seek(0)
    # Convert PNG image to base64 encoded string
    img_b64 = base64.b64encode(img.getvalue()).decode('utf-8')

    # Create an HTML element containing the base64 encoded image
    html = '<img src="data:image/png;base64,{}">'.format(img_b64)
    pie_chart_popup = folium.Popup(html=html, max_width=1500)

    # Add a marker for the pie chart on the map
    pie_chart_marker = folium.Marker([aoi.centroid().getInfo()['coordinates'][1]-0.005, aoi.centroid().getInfo()['coordinates'][0]], 
                                     popup=pie_chart_popup,
                                     icon=folium.Icon(icon="info-sign"))
    
    pie_chart_feature_group = folium.FeatureGroup(name='Pie Chart')
    pie_chart_marker.add_to(pie_chart_feature_group)
    
    return pie_chart_feature_group


def export_image_to_cloud_storage(export_params):
    """Export an ee.image to Cloud Storage.
    
    Args:
        export_params (dict): A dictionary containing the parameters for exporting an Earth Engine image to Cloud Storage.
            Keys:
                - image (ee.Image): The Earth Engine image to export.
                - description (str): A description for the export task.
                - bucket (str): The name of the Cloud Storage bucket to export the image to.
                - fileNamePrefix (str): The prefix to use for the output file name.
                - fileFormat (str): The file format to use for the output file.
                - region (ee.Geometry): The region to export the image from.
                - scale (int): The scale to export the image at.
    Returns:
        None
    """
    
    # Create a Cloud Storage client
    storage_client = storage.Client()

    # Define the export parameters
    task = ee.batch.Export.image.toCloudStorage(**export_params)
    task.start()
    
    # Wait for the task to complete
    start_time = time.time()
    while task.status()['state'] in ['RUNNING', 'READY']:
        elapsed_time = time.time() - start_time
        minutes, seconds = divmod(elapsed_time, 60)
        display_str = f'Exporting... Elapsed time: {int(minutes)}m {int(seconds)}s'
        clear_output(wait=True)
        display(display_str)
        time.sleep(0.1)

    # Check if the export completed successfully
    if task.status()['state'] == 'COMPLETED':
        display(f'Export completed')
        # Download the GeoTIFF file from Cloud Storage to local dir
        # display(f'Downloading file from Cloud Storage...')
        # bucket_name = export_params['bucket']
        # destination_blob_name = export_params['fileNamePrefix'] + '.tif'
        # blob = storage_client.get_bucket(bucket_name).blob(destination_blob_name)
        # blob.download_to_filename(destination_blob_name)
        # display(f'Saved file: {destination_blob_name}')
    else:
        error_message = task.status().get('error_message', 'Unknown error occurred.')
        display(f'Export failed. Error message: {error_message}')
        
          
def generate_examples(**kwargs):
    # Construct the command with the provided parameters
    cmd_params = [f"--{k}={v}" for k, v in kwargs.items()]
    command = ["python", "generate_examples_main.py"] + cmd_params
    
    # Run the command
    with open('skai_image_generation_output.txt', 'w') as f:
        subprocess.run(command, shell=False, check=True, stdout=f, stderr=f)
        
def launch_vertex_job(**kwargs):
    # Construct the command with the provided parameters
    cmd_params = [f"--{k}={v}" for k, v in kwargs.items()]
    command = ["python", "launch_vertex_job.py"] + cmd_params
    
    # Run the command
    with open('skai_prediction_output.txt', 'w') as f:
        subprocess.run(command, shell=False, check=True, stdout=f, stderr=f)

def run_command(file_name, **kwargs):
    # Construct the command with the provided parameters
    cmd_params = [f"--{k}={v}" for k, v in kwargs.items()]
    command = ["python", file_name] + cmd_params

    # Run the command
    with open('skai_command_output.txt', 'w') as f:
        subprocess.run(command, shell=False, check=True, stdout=f, stderr=f)