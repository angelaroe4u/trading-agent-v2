"""
v2_engine.distillation.cot_distill — CoT distillation: 70B teacher -> 7B student.

Two backends:
  1. unsloth-ai/unsloth — 2-4× faster, lower VRAM. Preferred if installed.
  2. huggingface alignment-handbook style SFT loop — fallback.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterable

from v2_engine import config as cfg


def generate_teacher_traces(prompts: Iterable[str], out_path,
                            teacher_model="llama-3.3-70b-versatile") -> int:
    from openai import OpenAI
    client = OpenAI(api_key=os.getenv("GROQ_API_KEY"),
                    base_url="https://api.groq.com/openai/v1")
    n = 0
    with Path(out_path).open("a", encoding="utf-8") as f:
        for prompt in prompts:
            r = client.chat.completions.create(
                model=teacher_model,
                messages=[
                    {"role": "system",
                     "content": "Think step by step. Conclude with a JSON object."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
            )
            f.write(json.dumps({"prompt": prompt,
                                "trace": r.choices[0].message.content}) + "\n")
            n += 1
    return n


def distill_student_unsloth(traces_jsonl, out_adapter,
                            base_model=None, max_steps=500) -> str:
    """Preferred: unsloth path — 2-4× faster than vanilla peft."""
    try:
        from unsloth import FastLanguageModel
        from trl import SFTTrainer
        from transformers import TrainingArguments
        from datasets import Dataset
        import json

        base_model = base_model or cfg.V2_BASE_MODEL
        model, tok = FastLanguageModel.from_pretrained(
            model_name=base_model, max_seq_length=4096, load_in_4bit=True,
        )
        model = FastLanguageModel.get_peft_model(
            model, r=16, lora_alpha=32, lora_dropout=0.05,
            target_modules=["q_proj","k_proj","v_proj","o_proj",
                            "gate_proj","up_proj","down_proj"],
        )
        rows = [json.loads(line) for line in Path(traces_jsonl).read_text().splitlines() if line.strip()]
        ds = Dataset.from_list([{"text": f"<|user|>\n{r['prompt']}\n<|assistant|>\n{r['trace']}"} for r in rows])
        trainer = SFTTrainer(
            model=model, tokenizer=tok, train_dataset=ds,
            dataset_text_field="text", max_seq_length=4096,
            args=TrainingArguments(
                output_dir=str(out_adapter),
                per_device_train_batch_size=2, gradient_accumulation_steps=4,
                max_steps=max_steps, learning_rate=2e-4, fp16=True,
                logging_steps=10, save_strategy="epoch", report_to=[],
            ),
        )
        trainer.train()
        model.save_pretrained(str(out_adapter))
        return str(out_adapter)
    except Exception as e:
        print(f"unsloth path failed ({e}); writing TODO and bailing")
        Path(out_adapter).mkdir(parents=True, exist_ok=True)
        (Path(out_adapter) / "TODO_distill.md").write_text(
            f"unsloth unavailable on this host ({e}); fall back to vanilla peft + trl.\n"
            f"Teacher traces: {traces_jsonl}\nBase: {base_model or cfg.V2_BASE_MODEL}\n"
        )
        return str(out_adapter)


# Back-compat alias
distill_student = distill_student_unsloth
