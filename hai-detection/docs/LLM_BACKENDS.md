# LLM Backend Configuration

This document describes how to configure and switch between LLM backends for HAI classification.

## Supported Backends

| Backend | Description | Use Case |
|---------|-------------|----------|
| `ollama` | Local inference via Ollama | Development, simple setup |
| `vllm` | High-throughput inference via vLLM | Production, better performance |
| `claude` | Anthropic Claude API | Not yet implemented |

## Switching Backends

Set the `LLM_BACKEND` environment variable or add to `.env`:

```bash
# Use Ollama (default)
export LLM_BACKEND=ollama

# Use vLLM
export LLM_BACKEND=vllm
```

## Ollama Configuration

### Environment Variables

```bash
export LLM_BACKEND=ollama
export OLLAMA_BASE_URL=http://localhost:11434  # Default
export OLLAMA_MODEL=llama3.3:70b               # Default
```

### Starting Ollama

```bash
# Start Ollama service
ollama serve

# Pull model (if not already downloaded)
ollama pull llama3.3:70b

# Check available models
ollama list
```

### Multi-GPU with Ollama

Ollama automatically uses tensor parallelism for large models. For llama3.3:70b with Q4_K_M quantization, it typically splits across available GPUs.

## vLLM Configuration

### Environment Variables

```bash
export LLM_BACKEND=vllm
export VLLM_BASE_URL=http://localhost:8000     # Default
export VLLM_MODEL=Qwen/Qwen2.5-72B-Instruct    # Default
```

### Starting vLLM Server

```bash
# Basic start (uses all available GPUs)
vllm serve Qwen/Qwen2.5-72B-Instruct

# With tensor parallelism across 2 GPUs
vllm serve Qwen/Qwen2.5-72B-Instruct --tensor-parallel-size 2

# Specific GPU assignment
CUDA_VISIBLE_DEVICES=0,1 vllm serve Qwen/Qwen2.5-72B-Instruct --tensor-parallel-size 2

# With custom port
vllm serve Qwen/Qwen2.5-72B-Instruct --port 8000

# With increased max model length (for long clinical notes)
vllm serve Qwen/Qwen2.5-72B-Instruct --max-model-len 32768
```

### vLLM Advantages

- **PagedAttention**: More efficient GPU memory management
- **Continuous batching**: Higher throughput for concurrent requests
- **OpenAI-compatible API**: Easy integration

## Benchmarking Models

Use the included test script to benchmark different models:

```bash
cd /home/david/projects/aegis/hai-detection

# Test with current backend (Ollama or vLLM)
python test_keyword_filtering.py

# Override backend for testing
LLM_BACKEND=vllm python test_keyword_filtering.py
LLM_BACKEND=ollama python test_keyword_filtering.py
```

### Test Script Details

The `test_keyword_filtering.py` script:
1. Creates a mock CLABSI candidate with 30 clinical notes
2. Notes are realistic length (2-3K chars each, ~50K total)
3. Tests with and without keyword filtering
4. Reports timing for LLM classification

### What the Test Measures

- **Note retrieval time**: Time to fetch and filter notes (typically < 1s)
- **LLM classification time**: End-to-end inference time
- **Content reduction**: How much keyword filtering reduces context size

---

## Model Benchmark Results

### Hardware

- **GPU 1**: NVIDIA RTX A6000 (48GB VRAM)
- **GPU 2**: NVIDIA RTX A5000 (24GB VRAM)
- **Total VRAM**: 72GB

### Benchmark: CLABSI Classification

Test case: 30 clinical notes, ~50K characters total context

| Backend | Model | Quantization | Notes | Context | Time | Notes |
|---------|-------|--------------|-------|---------|------|-------|
| Ollama | llama3.3:70b | Q4_K_M | 10 (filtered) | 25K chars | 84s | Keyword filtering ON |
| Ollama | llama3.3:70b | Q4_K_M | 19 (unfiltered) | 48K chars | 64s | Keyword filtering OFF |
| vLLM | Qwen/Qwen2.5-72B-Instruct | FP16 | - | - | TBD | Pending testing |

### Observations

1. **Fixed overhead dominates**: LLM inference time doesn't scale linearly with input size for moderate contexts (25K-50K chars)
2. **Quantization**: Q4_K_M provides good balance of speed and quality for 70B models
3. **Multi-GPU**: Both Ollama and vLLM support tensor parallelism for models that don't fit on single GPU

### Classification Quality

| Model | Decision Accuracy | Confidence Calibration | Notes |
|-------|-------------------|------------------------|-------|
| llama3.3:70b | Good | 0.90 typical | Reliable for CLABSI/CDI |
| Qwen2.5-72B-Instruct | TBD | TBD | Pending testing |

---

## Adding New Models

### Ollama

```bash
# Pull a new model
ollama pull <model-name>

# Update config
export OLLAMA_MODEL=<model-name>
```

### vLLM

```bash
# vLLM downloads from HuggingFace automatically
# Just update the model name in config or command line
export VLLM_MODEL=<org>/<model-name>

# Start server with new model
vllm serve <org>/<model-name> --tensor-parallel-size 2
```

### Recommended Models to Try

| Model | Size | Notes |
|-------|------|-------|
| `llama3.3:70b` | 70B | Current default, good quality |
| `Qwen/Qwen2.5-72B-Instruct` | 72B | Strong reasoning, good for clinical |
| `meta-llama/Llama-3.1-70B-Instruct` | 70B | Alternative to 3.3 |
| `mistralai/Mixtral-8x22B-Instruct-v0.1` | 141B (MoE) | May need more VRAM |
| `Qwen/Qwen2.5-32B-Instruct` | 32B | Faster, fits single GPU |

---

## Troubleshooting

### Ollama Issues

```bash
# Check if Ollama is running
curl http://localhost:11434/api/tags

# Check model availability
ollama list

# View logs
journalctl -u ollama -f
```

### vLLM Issues

```bash
# Check if vLLM server is running
curl http://localhost:8000/v1/models

# Common issues:
# - OOM: Reduce --max-model-len or use smaller model
# - Slow startup: First run downloads model from HuggingFace
# - Port conflict: Use --port to specify different port
```

### Memory Issues

If running out of GPU memory:

1. **Reduce max context length**: `--max-model-len 16384`
2. **Use quantized model** (Ollama): Models with Q4_K_M suffix
3. **Use smaller model**: 32B instead of 70B
4. **Check other GPU processes**: `nvidia-smi`
