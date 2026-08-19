import numpy as np
import cv2
from pathlib import Path


class EyeClassifier:
    def __init__(self, model_path):
        self._available = False
        self._interpreter = None
        self._input_details = None
        self._output_details = None

        path = Path(model_path)
        if not path.exists():
            print(f"[CLASSIFIER] Model not found at {path} — "
                  f"CNN inference disabled, falling back to EAR-only")
            return

        try:
            from ai_edge_litert.interpreter import Interpreter
            self._interpreter = Interpreter(model_path=str(path))
            self._interpreter.allocate_tensors()
            self._input_details = self._interpreter.get_input_details()
            self._output_details = self._interpreter.get_output_details()
            self._available = True
            print(f"[CLASSIFIER] Loaded model from {path} "
                  f"({path.stat().st_size / 1024:.1f} KB)")
        except Exception as e:
            print(f"[CLASSIFIER] Failed to load model: {e} — "
                  f"CNN inference disabled, falling back to EAR-only")
            self._available = False

    def is_available(self):
        return self._available

    def _preprocess_crop(self, crop):
        if crop is None:
            return None
        if crop.shape != (32, 64):
            crop = cv2.resize(crop, (64, 32))
        crop = crop.astype(np.float32) / 255.0
        crop = (crop - 0.5) / 0.5   # normalize to [-1, 1] matching training
        crop = crop.reshape(1, 1, 32, 64)
        return crop

    def predict(self, left_crop, right_crop):
        if not self._available or self._interpreter is None:
            return None

        probs = []
        input_idx = self._input_details[0]["index"]
        output_idx = self._output_details[0]["index"]

        for crop in (left_crop, right_crop):
            processed = self._preprocess_crop(crop)
            if processed is None:
                continue

            self._interpreter.set_tensor(input_idx, processed)
            self._interpreter.invoke()
            logits = self._interpreter.get_tensor(output_idx)[0]

            exp = np.exp(logits - np.max(logits))
            softmax = exp / np.sum(exp)
            probs.append(float(softmax[1]))

        if not probs:
            return None
        return max(probs)
