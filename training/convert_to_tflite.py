import argparse
import torch
from pathlib import Path

from training.eye_cnn import EyeCNN


def main():
    parser = argparse.ArgumentParser(
        description="Export trained EyeCNN to TensorFlow Lite"
    )
    parser.add_argument("--model", required=True,
                        help="Path to .pth checkpoint file")
    parser.add_argument("--output", default="models/eye_state.tflite",
                        help="Output .tflite file path")
    args = parser.parse_args()

    model_path = Path(args.model)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"[CONVERT] Loading model from {model_path}")
    device = torch.device("cpu")
    model = EyeCNN()
    state_dict = torch.load(model_path, map_location=device, weights_only=True)
    model.load_state_dict(state_dict)
    model.eval()

    print("[CONVERT] Converting to TFLite via ai-edge-torch ...")
    import ai_edge_torch
    sample_input = (torch.randn(1, 1, 32, 64),)
    edge_model = ai_edge_torch.convert(model.eval(), sample_input)
    edge_model.export(str(output_path))

    size_kb = output_path.stat().st_size / 1024
    print(f"[CONVERT] Exported to {output_path} ({size_kb:.1f} KB)")
    print(f"[CONVERT] Done.")


if __name__ == "__main__":
    main()
