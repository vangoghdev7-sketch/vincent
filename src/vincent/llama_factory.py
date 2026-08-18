"""
Vincent CLI 4.0 — LlamaFactory Training & Fine-Tuning Integration (hiyouga/LlamaFactory).
Provides native hooks for LoRA, QLoRA, full fine-tuning, and dataset preparation
directly through the Vincent interactive CLI.
"""

import os
import json
import time
import yaml
from typing import Dict, Any, List, Optional

DEFAULT_TRAIN_DIR = os.path.expanduser("~/.vincent/training")

class LlamaFactoryOrchestrator:
    """Orquestrador de Fine-Tuning e Treinamento de LLMs Locais."""

    def __init__(self, work_dir: str = DEFAULT_TRAIN_DIR):
        self.work_dir = work_dir
        os.makedirs(self.work_dir, exist_ok=True)

    def generate_lora_config(
        self,
        base_model: str = "qwen3:0.6b",
        dataset_name: str = "vincent_esp32_dataset",
        lora_rank: int = 16,
        lora_alpha: int = 32,
        learning_rate: float = 2e-4,
        epochs: int = 3,
        output_dir: Optional[str] = None
    ) -> str:
        """
        Gera arquivo de configuração YAML compatível com o padrão LlamaFactory.
        """
        out_dir = output_dir or os.path.join(self.work_dir, f"lora_{int(time.time())}")
        
        config = {
            "stage": "sft",
            "do_train": True,
            "model_name_or_path": base_model,
            "dataset": dataset_name,
            "dataset_dir": os.path.join(self.work_dir, "data"),
            "template": "qwen",
            "finetuning_type": "lora",
            "lora_target": "all",
            "lora_rank": lora_rank,
            "lora_alpha": lora_alpha,
            "lora_dropout": 0.05,
            "output_dir": out_dir,
            "overwrite_output_dir": True,
            "per_device_train_batch_size": 2,
            "gradient_accumulation_steps": 4,
            "learning_rate": learning_rate,
            "num_train_epochs": epochs,
            "lr_scheduler_type": "cosine",
            "warmup_ratio": 0.1,
            "fp16": True,
            "logging_steps": 10,
            "save_steps": 100,
            "plot_loss": True
        }

        config_path = os.path.join(self.work_dir, "train_lora.yaml")
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(config, f, default_flow_style=False)

        return config_path

    def export_session_dataset(self, history: List[Dict[str, str]], filename: str = "session_dataset.json") -> str:
        """
        Exporta o histórico da sessão de chat em formato de dataset instrucional (ShareGPT/Alpaca format).
        """
        dataset_dir = os.path.join(self.work_dir, "data")
        os.makedirs(dataset_dir, exist_ok=True)
        file_path = os.path.join(dataset_dir, filename)

        formatted_conversations = []
        user_msg = ""
        for msg in history:
            role = msg.get("role")
            content = msg.get("content", "")
            if role == "user":
                user_msg = content
            elif role == "assistant" and user_msg:
                formatted_conversations.append({
                    "instruction": user_msg,
                    "input": "",
                    "output": content
                })
                user_msg = ""

        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(formatted_conversations, f, indent=2, ensure_ascii=False)

        return file_path

    def build_training_command(self, config_path: str) -> str:
        """Gera a linha de comando para iniciar o treino via llamafactory-cli ou python."""
        return f"llamafactory-cli train {config_path}"
