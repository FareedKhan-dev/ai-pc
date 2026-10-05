"""Convert TinyClick from the original Florence-2 code's format to the Florence-2 built into transformers, so the model
loads with no downloaded code (no trust_remote_code).

  python services/tinyclick/model.py --download-only   # the original weights, into ./models/hf
  python services/tinyclick/convert.py                 # writes ./models/tinyclick

The weights are only renamed, with three changes the built-in code needs: the image projection is transposed for
nn.Linear, the vocabulary gets one row for the <image> placeholder (never generated), and the output layer is the word
embeddings, as the original code ties them when it loads (the checkpoint's separate lm_head tensor is never used).
"""

import json
import os
import re
from pathlib import Path

ROOT = Path(os.environ.get("AI_PC_HOME") or Path(__file__).resolve().parents[2])
os.environ["HF_HOME"] = str(ROOT / "models" / "hf")
os.environ["HF_HUB_OFFLINE"] = "1"  # convert what is already downloaded; never fetch
OUT = ROOT / "models" / "tinyclick"
REPO = "Krystianz/TinyClick"
IMAGE_TOKEN = "<image>"

RENAMES = [  # original name -> built-in name, applied in order
    (r"^vision_tower\.convs\.(\d+)\.proj\.", r"vision_tower.convs.\1.conv."),
    (r"\.(conv[12])\.fn\.dw\.", r".\1."),
    (r"\.(window_attn|channel_attn)\.norm\.", ".norm1."),
    (r"\.(window_attn|channel_attn)\.fn\.", r".\1."),
    (r"\.ffn\.norm\.", ".norm2."),
    (r"\.ffn\.fn\.net\.", ".ffn."),
    (r"^vision_tower\.", "model.vision_tower."),
    (r"^image_pos_embed\.", "model.multi_modal_projector.image_position_embed."),
    (r"^image_proj_norm\.", "model.multi_modal_projector.image_proj_norm."),
    (r"^visual_temporal_embed\.", "model.multi_modal_projector.visual_temporal_embed."),
    (r"^language_model\.model\.", "model.language_model."),
]


def configs(src):
    from transformers import BartConfig, Florence2Config, Florence2VisionConfig

    v, t = src["vision_config"], src["text_config"]
    vision = Florence2VisionConfig(
        depths=v["depths"],
        embed_dim=v["dim_embed"],
        num_heads=v["num_heads"],
        num_groups=v["num_groups"],
        patch_size=v["patch_size"],
        patch_stride=v["patch_stride"],
        patch_padding=v["patch_padding"],
        patch_prenorm=v["patch_prenorm"],
        window_size=v["window_size"],
        drop_path_rate=v["drop_path_rate"],
        projection_dim=v["projection_dim"],
        max_temporal_embeddings=v["visual_temporal_embedding"]["max_temporal_embeddings"],
        max_position_embeddings=v["image_pos_embed"]["max_pos_embeddings"],
    )
    text = BartConfig(
        vocab_size=t["vocab_size"] + 1,  # + <image>
        d_model=t["d_model"],
        encoder_layers=t["encoder_layers"],
        decoder_layers=t["decoder_layers"],
        encoder_attention_heads=t["encoder_attention_heads"],
        decoder_attention_heads=t["decoder_attention_heads"],
        encoder_ffn_dim=t["encoder_ffn_dim"],
        decoder_ffn_dim=t["decoder_ffn_dim"],
        activation_function=t["activation_function"],
        max_position_embeddings=t["max_position_embeddings"],
        scale_embedding=t["scale_embedding"],
        pad_token_id=t["pad_token_id"],
        bos_token_id=t["bos_token_id"],
        eos_token_id=t["eos_token_id"],
        decoder_start_token_id=t["decoder_start_token_id"],
    )
    return Florence2Config(text_config=text, vision_config=vision, image_token_id=t["vocab_size"])


def weights(path, image_token_id):
    import torch
    from safetensors import safe_open

    out = {}
    with safe_open(str(path), "pt") as f:
        for name in f.keys():
            x = f.get_tensor(name)
            if name == "language_model.final_logits_bias":
                if x.abs().max() != 0:
                    raise SystemExit("final_logits_bias is not zero: the built-in model has no place for it")
                continue
            if name == "language_model.lm_head.weight":
                continue  # the original code ties the output layer to the word embeddings when it loads
            if name == "image_projection":
                out["model.multi_modal_projector.image_projection.weight"] = x.t().contiguous()
                continue
            if name == "language_model.model.shared.weight":
                if x.shape[0] != image_token_id:
                    raise SystemExit(f"expected {image_token_id} words in the vocabulary, found {x.shape[0]}")
                x = torch.cat([x, x.new_zeros(1, x.shape[1])])  # the <image> row: replaced by image features
                for tied in (
                    "model.language_model.encoder.embed_tokens.weight",
                    "model.language_model.decoder.embed_tokens.weight",
                    "lm_head.weight",
                ):
                    out[tied] = x
            for pattern, repl in RENAMES:
                name = re.sub(pattern, repl, name)
            out[name] = x
    return out


def main():
    from huggingface_hub import snapshot_download
    from transformers import CLIPImageProcessorPil, Florence2ForConditionalGeneration, Florence2Processor, GenerationConfig
    from transformers.models.bart import BartTokenizer

    src = Path(snapshot_download(REPO, local_files_only=True))
    config = configs(json.loads((src / "config.json").read_text(encoding="utf-8")))
    model = Florence2ForConditionalGeneration(config)
    result = model.load_state_dict(weights(src / "model.safetensors", config.image_token_id), strict=True)
    print(f"weights: {len(model.state_dict())} tensors loaded, {result}")
    gen = json.loads((src / "generation_config.json").read_text(encoding="utf-8"))
    model.generation_config = GenerationConfig(
        **{k: v for k, v in gen.items() if not k.startswith("_") and k != "transformers_version"},
        suppress_tokens=[config.image_token_id],
    )
    model.eval().save_pretrained(OUT)

    tokenizer = BartTokenizer.from_pretrained(src, extra_special_tokens={"image_token": IMAGE_TOKEN})
    if tokenizer.image_token_id != config.image_token_id:
        raise SystemExit(f"{IMAGE_TOKEN} got id {tokenizer.image_token_id}, the model expects {config.image_token_id}")
    pre = json.loads((src / "preprocessor_config.json").read_text(encoding="utf-8"))
    images = CLIPImageProcessorPil(  # the PIL resizing the original processor used
        do_resize=pre["do_resize"],
        size=pre["size"],
        resample=pre["resample"],
        do_center_crop=pre["do_center_crop"],
        do_rescale=pre["do_rescale"],
        rescale_factor=pre["rescale_factor"],
        do_normalize=pre["do_normalize"],
        image_mean=pre["image_mean"],
        image_std=pre["image_std"],
    )
    images.image_seq_length = pre["image_seq_length"]
    Florence2Processor(image_processor=images, tokenizer=tokenizer).save_pretrained(OUT)
    print(f"saved {OUT}")


if __name__ == "__main__":
    main()
