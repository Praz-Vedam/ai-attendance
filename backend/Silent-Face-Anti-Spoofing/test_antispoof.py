import os
import cv2
import numpy as np

from src.anti_spoof_predict import AntiSpoofPredict
from src.generate_patches import CropImage
from src.utility import parse_model_name

model_dir = "./resources/anti_spoof_models"

device_id = 0

model_test = AntiSpoofPredict(device_id)

image_name = "test_images/fake_photo.jpeg"

image = cv2.imread(image_name)

prediction = np.zeros((1, 3))

for model_name in os.listdir(model_dir):

    h_input, w_input, model_type, scale = parse_model_name(model_name)

    cropper = CropImage()

    param = {
        "org_img": image,
        "bbox": model_test.get_bbox(image),
        "scale": scale,
        "out_w": w_input,
        "out_h": h_input,
        "crop": True,
    }

    img = cropper.crop(**param)

    prediction += model_test.predict(
        img,
        os.path.join(model_dir, model_name)
    )

label = np.argmax(prediction)

value = prediction[0][label] / 2

print("\nPrediction Scores:")
print(prediction)

if label == 1:
    print(f"\nREAL FACE DETECTED | Confidence: {value:.2f}")
else:
    print(f"\nFAKE FACE DETECTED | Confidence: {value:.2f}")