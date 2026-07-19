# AI Engineer Guidebook
## Everything You Need to Know for the Red Hat Senior Software Engineer (AI/Agentic AI) Role

*Written in plain English. Start from the top, work your way down.*

---

## Table of Contents

1. [The Big Picture](#1-the-big-picture)
2. [Python for AI/ML](#2-python-for-aiml)
3. [PyTorch from Scratch](#3-pytorch-from-scratch)
4. [How LLMs Work (The Basics)](#4-how-llms-work)
5. [LLM Inference Optimization](#5-llm-inference-optimization)
6. [vLLM: Serving LLMs Fast](#6-vllm-serving-llms-fast)
7. [llm-d: Kubernetes-Native LLM Serving](#7-llm-d-kubernetes-native-llm-serving)
8. [Red Hat OpenShift AI](#8-red-hat-openshift-ai)
9. [Agentic AI: The New Paradigm](#9-agentic-ai-the-new-paradigm)
10. [Kubernetes for AI Workloads](#10-kubernetes-for-ai-workloads)
11. [Putting It All Together](#11-putting-it-all-together)
12. [Interview Prep Checklist](#12-interview-prep-checklist)
13. [Hands-On Projects](#13-hands-on-projects)
14. [Resources](#14-resources)

---

## 1. The Big Picture

This role sits at the intersection of three things:

```
AI/ML Knowledge ──────┐
                      ├──> This Role
Kubernetes/OpenShift ─┘
         │
    Software Engineering (Python/Go, APIs, Testing)
```

You are NOT expected to be an ML researcher who trains models from scratch.
You ARE expected to be an engineer who can:
- Deploy and serve AI models on Kubernetes
- Build agentic AI features into products
- Understand how models work well enough to optimize and debug them
- Write production-quality Python/Go code

Think of it like this: if data scientists build the engine, you build the car around it.

---

## 2. Python for AI/ML

You already know Python (Workstream, FastAPI). Here is what is different in AI/ML Python.

### Key Libraries You Must Know

| Library | What It Does | Learn It? |
|---------|-------------|-----------|
| **PyTorch** | Build and run neural networks | YES -- core requirement |
| **Hugging Face Transformers** | Load pre-trained models easily | YES -- you will use this daily |
| **NumPy** | Fast math on arrays (tensors are built on this idea) | Refresh if needed |
| **FastAPI** | Build API servers (you know this already) | Already know |
| **Pydantic** | Data validation (used everywhere in AI APIs) | Already know |
| **LangChain / LangGraph** | Build LLM-powered applications and agents | YES -- you have the cert |

### Quick Setup

```bash
# Create a clean environment
python3 -m venv ai-env
source ai-env/bin/activate

# Install the essentials
pip install torch torchvision transformers accelerate
pip install langchain langgraph langchain-community
pip install huggingface_hub datasets
pip install vllm  # for serving
```

---

## 3. PyTorch from Scratch

PyTorch is the most important technical skill for this role. Do not panic -- it is simpler than it looks.

### What is PyTorch?

PyTorch is a library that lets you do math on GPUs and automatically compute gradients (the math behind training neural networks). That is it. Everything else is built on top of these two ideas.

### Concept 1: Tensors

A tensor is just a multi-dimensional array. Think of it like a spreadsheet that can have more than 2 dimensions.

```python
import torch

# A single number (0 dimensions)
scalar = torch.tensor(42)

# A list of numbers (1 dimension) -- like a row in a spreadsheet
vector = torch.tensor([1, 2, 3, 4])

# A table of numbers (2 dimensions) -- like a spreadsheet
matrix = torch.tensor([[1, 2], [3, 4], [5, 6]])

# A 3D tensor -- like a stack of spreadsheets
cube = torch.tensor([[[1, 2], [3, 4]], [[5, 6], [7, 8]]])

# Check shape -- this is the most common debugging step in AI
print(matrix.shape)  # torch.Size([3, 2]) = 3 rows, 2 columns
```

**GPU acceleration** -- the reason AI is fast:

```python
# Move a tensor to GPU
if torch.cuda.is_available():
    tensor = tensor.to("cuda")  # now it runs on GPU

# Move back to CPU
tensor = tensor.to("cpu")
```

### Concept 2: Autograd (Automatic Gradients)

Training a model means adjusting numbers (weights) to reduce errors. Gradients tell you which direction to adjust. PyTorch computes these automatically.

```python
# Create a tensor that tracks gradients
x = torch.tensor(3.0, requires_grad=True)

# Do some math
y = x ** 2 + 2 * x + 1  # y = x² + 2x + 1

# Compute the gradient (dy/dx = 2x + 2 = 8 when x=3)
y.backward()
print(x.grad)  # tensor(8.)  -- PyTorch figured this out automatically
```

### Concept 3: Building a Model

Every PyTorch model is a Python class that inherits from `nn.Module`:

```python
import torch.nn as nn

class SimpleModel(nn.Module):
    def __init__(self):
        super().__init__()
        self.layer1 = nn.Linear(10, 64)   # 10 inputs -> 64 hidden
        self.layer2 = nn.Linear(64, 32)   # 64 hidden -> 32 hidden
        self.layer3 = nn.Linear(32, 1)    # 32 hidden -> 1 output
        self.relu = nn.ReLU()             # activation function

    def forward(self, x):
        x = self.relu(self.layer1(x))
        x = self.relu(self.layer2(x))
        return self.layer3(x)

model = SimpleModel()
print(model)  # see the architecture
```

### Concept 4: The Training Loop

Every training loop in PyTorch follows the same 5 steps. Memorize this pattern:

```python
model = SimpleModel()
optimizer = torch.optim.Adam(model.parameters(), lr=0.001)
loss_fn = nn.MSELoss()

for epoch in range(100):
    for data, target in dataloader:
        # Step 1: Clear old gradients
        optimizer.zero_grad(set_to_none=True)

        # Step 2: Forward pass (make a prediction)
        prediction = model(data)

        # Step 3: Compute the loss (how wrong was the prediction?)
        loss = loss_fn(prediction, target)

        # Step 4: Backward pass (compute gradients)
        loss.backward()

        # Step 5: Update weights
        optimizer.step()
```

### Concept 5: Inference (Using a Trained Model)

```python
model.eval()  # switch to evaluation mode (disables dropout etc.)

with torch.inference_mode():  # no gradient tracking = faster + less memory
    result = model(input_data)
```

### Key Optimization: torch.compile

```python
# One line for 20-50% speedup. This is the recommended approach in 2026.
compiled_model = torch.compile(model)
```

---

## 4. How LLMs Work

You don't need to build an LLM from scratch. But you need to understand the basic ideas well enough to debug, optimize, and talk about them.

### The Transformer Architecture (Simplified)

Every modern LLM (GPT, Llama, Gemini) is based on the Transformer. Here is how it works in plain English:

```
Input: "The cat sat on the"
   │
   ▼
[Tokenizer] -- breaks text into pieces ("tokens")
   │
   ▼ tokens: [The, cat, sat, on, the]
   │
[Embedding Layer] -- converts each token into a vector of numbers
   │
   ▼ each token becomes a list of 4096 numbers
   │
[Attention Layers] x 32 (or 80, or 128...)
   │  Each layer asks: "which other tokens should I pay attention to?"
   │  "sat" pays attention to "cat" (who sat?) and "on" (sat where?)
   │
   ▼
[Output Layer] -- predicts the next token
   │
   ▼ "mat" (probability 0.15), "floor" (0.10), "rug" (0.08)...
```

### Key Terms You Must Know

| Term | Plain English |
|------|-------------|
| **Token** | A piece of text (roughly a word or part of a word). "unhappiness" might be 3 tokens: "un", "happi", "ness" |
| **Embedding** | Converting a token into a list of numbers that captures its meaning |
| **Attention** | The mechanism that lets each token "look at" other tokens to understand context |
| **KV Cache** | A memory optimization -- stores computed attention values so we don't recompute them |
| **Parameters** | The numbers inside the model that were learned during training. "70B" = 70 billion parameters |
| **Inference** | Using a trained model to generate text (no training involved) |
| **Fine-tuning** | Taking a pre-trained model and training it a bit more on your specific data |
| **LoRA/QLoRA** | Efficient fine-tuning that only changes a small part of the model |
| **Quantization** | Storing model weights in lower precision (e.g., FP16 -> INT4) to use less memory |
| **Context window** | How many tokens the model can process at once (e.g., 128K tokens) |

### How Text Generation Works (Step by Step)

LLMs generate text one token at a time:

```
Input: "The cat"
Step 1: Model reads "The cat" -> predicts "sat" -> Output: "The cat sat"
Step 2: Model reads "The cat sat" -> predicts "on" -> Output: "The cat sat on"
Step 3: Model reads "The cat sat on" -> predicts "the" -> Output: "The cat sat on the"
Step 4: Model reads "The cat sat on the" -> predicts "mat" -> Output: "The cat sat on the mat"
```

This is called **autoregressive generation**. It is sequential by nature -- each token depends on all previous tokens. This is why LLM inference is slow and why we need optimization.

### Using Hugging Face Transformers (The Practical Way)

```python
from transformers import AutoModelForCausalLM, AutoTokenizer

# Load a model (this downloads it from Hugging Face)
model_name = "meta-llama/Llama-3.1-8B-Instruct"
tokenizer = AutoTokenizer.from_pretrained(model_name)
model = AutoModelForCausalLM.from_pretrained(model_name, torch_dtype=torch.float16)
model.to("cuda")

# Generate text
inputs = tokenizer("The future of AI is", return_tensors="pt").to("cuda")
outputs = model.generate(**inputs, max_new_tokens=50)
print(tokenizer.decode(outputs[0]))
```

---

## 5. LLM Inference Optimization

This is a core topic for the interview. The question is: "How do we make LLMs faster and cheaper to run?"

There are three main techniques. Think of them as solving three different problems.

### Problem 1: "We keep recomputing the same thing" -> KV Cache

Every time the model generates a new token, it needs to look at all previous tokens using "attention." Without caching, it recomputes everything from scratch.

**KV Cache** stores the Key and Value matrices from previous tokens so we only compute attention for the new token.

```
Without KV Cache:  Generate token 100 -> recompute all 99 previous tokens
With KV Cache:     Generate token 100 -> only compute for token 100, reuse cached 99
```

**PagedAttention** (vLLM's key innovation): manages KV Cache like virtual memory in an operating system. Instead of pre-allocating one big block per request, it uses small "pages" that can be scattered in memory. This eliminates wasted space.

```
Before PagedAttention:  [Request A: ████████░░░░] [Request B: ██████░░░░░░]
                         ^^^^^^^^ used    ^^^^ wasted

After PagedAttention:   [A][B][A][B][A][A][B][B]  -- no wasted space
```

### Problem 2: "The model is too big for our GPU" -> Quantization

A 70B parameter model in FP16 needs ~140GB of GPU memory. Most GPUs have 40-80GB.

**Quantization** reduces the precision of the numbers:
- FP32 (32 bits per number) -> largest, most precise
- FP16 (16 bits) -> half the size, almost no quality loss
- INT8 (8 bits) -> quarter the size, tiny quality loss
- INT4 (4 bits) -> 1/8th the size, small quality loss

```
70B model:
  FP32: ~280 GB (needs 4+ GPUs)
  FP16: ~140 GB (needs 2 GPUs)
  INT8:  ~70 GB (fits on 1 GPU)
  INT4:  ~35 GB (fits on 1 consumer GPU)
```

Common methods: **GPTQ**, **AWQ**, **bitsandbytes**, **FP8** (supported natively in newer GPUs)

### Problem 3: "One token at a time is slow" -> Speculative Decoding

Normal generation: produce 1 token per forward pass.

Speculative decoding uses a trick:
1. A small, fast "draft" model guesses 5-10 tokens ahead
2. The big model checks all guesses in ONE forward pass (verification is parallel)
3. Correct guesses are kept. First wrong guess triggers a fix.

```
Normal:      [generate 1] [generate 2] [generate 3] [generate 4] [generate 5]
             5 forward passes of big model

Speculative: [draft guesses: 1,2,3,4,5] [big model verifies all 5 at once]
             1 forward pass of draft + 1 forward pass of big model
             If 4 out of 5 are correct -> 4 tokens for the cost of ~2 passes
```

Result: 2-3x speedup with zero quality loss.

### Summary: The Three Pillars

| Technique | Problem It Solves | Speedup |
|-----------|------------------|---------|
| **KV Cache + PagedAttention** | Recomputing attention | Fundamental (everyone uses it) |
| **Quantization** | Model too big for GPU memory | 2-4x memory reduction |
| **Speculative Decoding** | One-token-at-a-time bottleneck | 2-3x faster generation |

### Key Metrics to Know

| Metric | What It Measures |
|--------|-----------------|
| **TTFT** (Time to First Token) | How long until the user sees the first word |
| **TPOT** (Time Per Output Token) | How fast tokens stream after the first one |
| **Throughput** (tokens/second) | Total tokens generated per second across all users |
| **Cost per token** | How much each generated token costs in compute |

---

## 6. vLLM: Serving LLMs Fast

vLLM is the most popular open-source LLM serving engine. Red Hat heavily invests in it. This is a must-know for the role.

### What vLLM Does

vLLM takes a model from Hugging Face and turns it into a high-performance API server. Think of it as "nginx for LLMs."

### Key Features

1. **PagedAttention** -- efficient KV cache management (explained above)
2. **Continuous batching** -- dynamically groups incoming requests together instead of waiting for a fixed batch
3. **OpenAI-compatible API** -- drop-in replacement for OpenAI's API
4. **Quantization support** -- FP8, INT8, INT4, GPTQ, AWQ out of the box
5. **Speculative decoding** -- built-in
6. **Tensor parallelism** -- split one model across multiple GPUs
7. **200+ model architectures** -- Llama, Mistral, Qwen, DeepSeek, etc.

### How to Use vLLM

**Install:**
```bash
pip install vllm
```

**Serve a model (one command):**
```bash
vllm serve meta-llama/Llama-3.1-8B-Instruct \
    --tensor-parallel-size 2 \
    --max-model-len 8192 \
    --dtype float16
```

This starts an OpenAI-compatible server at `http://localhost:8000`.

**Send a request:**
```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "meta-llama/Llama-3.1-8B-Instruct",
    "messages": [{"role": "user", "content": "Explain KV cache in one sentence"}],
    "max_tokens": 100
  }'
```

**Use in Python:**
```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:8000/v1", api_key="dummy")
response = client.chat.completions.create(
    model="meta-llama/Llama-3.1-8B-Instruct",
    messages=[{"role": "user", "content": "Explain KV cache in one sentence"}],
)
print(response.choices[0].message.content)
```

### vLLM Architecture (2026 -- Model Runner V2)

```
Request comes in
      │
      ▼
[Tokenizer] -- converts text to token IDs
      │
      ▼
[Scheduler] -- decides which requests to process together
      │         uses continuous batching (no waiting for a full batch)
      ▼
[Model Runner V2] -- runs the actual model on GPU
      │  - GPU-native input preparation (Triton kernels)
      │  - Async scheduling (CPU prepares step N+1 while GPU runs step N)
      │  - PagedAttention for KV cache
      │  - CUDA graphs for fast execution
      ▼
[Sampler] -- picks the next token from probabilities
      │
      ▼
[Detokenizer] -- converts token IDs back to text
      │
      ▼
Response sent back (or streamed token by token)
```

### Key vLLM Commands to Know

```bash
# Serve with quantization
vllm serve model-name --quantization awq

# Serve with speculative decoding
vllm serve big-model --speculative-config '{"method":"draft_model","model":"small-model","num_speculative_tokens":5}'

# Serve across 4 GPUs
vllm serve model-name --tensor-parallel-size 4

# Enable prefix caching (reuse KV cache for repeated prompts)
vllm serve model-name --enable-prefix-caching

# Set max concurrent requests
vllm serve model-name --max-num-seqs 256
```

---

## 7. llm-d: Kubernetes-Native LLM Serving

llm-d is Red Hat's project for running LLM inference on Kubernetes at scale. It is a CNCF Sandbox project (founded by Red Hat, Google Cloud, IBM, CoreWeave, NVIDIA). This is very likely to come up in the interview.

### The Problem llm-d Solves

vLLM is great for running a model on one machine. But in production you have:
- Multiple GPU nodes
- Many models to serve
- Traffic that spikes and drops
- Need to optimize cost (GPUs are expensive)

llm-d adds the Kubernetes orchestration layer on top of vLLM.

### How llm-d Works

```
User Request
      │
      ▼
[Inference Gateway (IGW)]  -- Kubernetes Gateway API extension
      │  - Routes requests to the right model
      │  - KV-cache-aware routing (send to the node that already has context)
      │  - Smart load balancing
      ▼
[llm-d Router]
      │  - Knows which vLLM instances have which KV cache
      │  - Routes to minimize TTFT and maximize cache reuse
      ▼
[vLLM Instance 1]  [vLLM Instance 2]  [vLLM Instance 3]
(prefill worker)   (decode worker)     (decode worker)
      │                   │                   │
  [GPU Node 1]       [GPU Node 2]       [GPU Node 3]
```

### Key Concepts

**Disaggregated Serving:**
Instead of every instance doing both prefill (processing the prompt) and decode (generating tokens), llm-d can split them:
- **Prefill instances**: process incoming prompts (compute-heavy, bursty)
- **Decode instances**: generate tokens (memory-heavy, steady)

This is like having separate highway lanes for trucks and cars.

**KV-Cache-Aware Routing:**
When a user sends a follow-up message, the router sends it to the same vLLM instance that already has the conversation's KV cache in memory. No re-processing needed.

**Deployment with Helm:**
```yaml
# llm-d uses a custom resource called LLMInferenceService
apiVersion: llm-d.ai/v1
kind: LLMInferenceService
metadata:
  name: llama-3-70b
spec:
  model: meta-llama/Llama-3.1-70B-Instruct
  replicas: 3
  accelerator: nvidia-a100-80gb
  disaggregated:
    prefill:
      replicas: 1
    decode:
      replicas: 2
```

### Performance Claims
- 3x higher output throughput vs. round-robin routing
- 2x faster TTFT with prefix-cache-aware routing

---

## 8. Red Hat OpenShift AI

OpenShift AI (RHOAI) is Red Hat's enterprise AI platform built on OpenShift. It is the productized version of the open-source Open Data Hub.

### What It Includes

```
┌─────────────────────────────────────────────┐
│              OpenShift AI                     │
│                                               │
│  [Workbenches]  -- Jupyter notebooks          │
│  [Pipelines]    -- ML training pipelines      │
│  [Model Serving] -- KServe + vLLM + llm-d     │
│  [Model Registry] -- track model versions     │
│  [Dashboard]    -- web UI for all of above     │
│                                               │
│  Built on: OpenShift (Kubernetes)             │
└─────────────────────────────────────────────┘
```

### Model Serving on OpenShift AI

This is the most relevant part for the role. OpenShift AI uses **KServe** to serve models.

**Two deployment modes:**

| Mode | How It Works | When to Use |
|------|-------------|-------------|
| **Serverless** (Advanced) | Uses Knative, can scale to zero | Cost-sensitive, bursty traffic |
| **RawDeployment** (Standard) | Uses regular K8s Deployments | Full control, steady traffic |

**Example InferenceService:**
```yaml
apiVersion: serving.kserve.io/v1beta1
kind: InferenceService
metadata:
  name: llama-3-8b
  annotations:
    serving.kserve.io/deploymentMode: RawDeployment
spec:
  predictor:
    model:
      modelFormat:
        name: vLLM
      runtime: vllm-runtime
      storageUri: s3://models/llama-3-8b
      resources:
        limits:
          cpu: "8"
          memory: "32Gi"
          nvidia.com/gpu: "1"
        requests:
          cpu: "8"
          memory: "32Gi"
          nvidia.com/gpu: "1"
```

### How It Connects to the Role

The job says "Design and develop robust, scalable, and production-ready solutions suitable for deployment within enterprise Kubernetes environments." This means:
- Building features that deploy as containers on OpenShift
- Using KServe/llm-d for model serving
- Understanding GPU scheduling, resource limits, autoscaling

---

## 9. Agentic AI: The New Paradigm

This is the core of the role. "Integrate Agentic AI functionality into Red Hat's AI product portfolio."

### What is an AI Agent?

A regular LLM is like a person who can only talk.
An AI agent is like a person who can talk AND use tools AND make plans AND take actions.

```
Regular LLM:
  User: "What's the weather in Boston?"
  LLM:  "I don't have access to real-time data, but typically..."

AI Agent:
  User: "What's the weather in Boston?"
  Agent: [thinks: I need weather data]
         [calls weather API tool]
         [gets result: 72°F, sunny]
  Agent: "It's 72°F and sunny in Boston right now."
```

### The 4 Agentic Patterns (Know These for the Interview)

**Pattern 1: Tool Use**
The agent calls external tools (APIs, databases, code execution).
```
Agent -> "I need to search" -> [Search Tool] -> gets results -> uses in response
```

**Pattern 2: Planning (ReAct)**
The agent breaks a complex task into steps:
```
Task: "Book me a flight from Boston to London under $500"
Plan: 1. Search flights Boston -> London
      2. Filter by price < $500
      3. Compare options
      4. Present best options to user
```

**Pattern 3: Reflection**
The agent reviews its own output and improves it:
```
Draft answer -> [Self-Review Agent] -> "This misses X, let me fix it" -> Better answer
```

**Pattern 4: Multi-Agent**
Multiple specialized agents collaborate:
```
[Planner Agent] -- decides what to do
      │
      ├── [Research Agent] -- gathers information
      ├── [Code Agent] -- writes code
      └── [Review Agent] -- checks quality
```

### Key Standards (You Already Know These from Workstream)

| Standard | What It Does |
|----------|-------------|
| **MCP** (Model Context Protocol) | Connects agents to external tools and data sources |
| **A2A** (Agent-to-Agent) | Lets agents communicate with each other |
| **AOP** (Agent Observability Protocol) | Monitors and traces agent behavior |

### Building an Agent with LangGraph

```python
from langgraph.graph import StateGraph, END
from langchain_openai import ChatOpenAI
from langchain.tools import tool

@tool
def search_web(query: str) -> str:
    """Search the web for information."""
    # actual implementation here
    return f"Results for: {query}"

@tool
def run_code(code: str) -> str:
    """Execute Python code."""
    return eval(code)

# Define the agent state
class AgentState(TypedDict):
    messages: list
    next_action: str

# Build the graph
graph = StateGraph(AgentState)
graph.add_node("reason", reason_node)      # LLM decides what to do
graph.add_node("use_tool", tool_node)       # Execute the chosen tool
graph.add_node("respond", respond_node)     # Generate final response

graph.add_edge("reason", "use_tool")
graph.add_conditional_edges("use_tool", should_continue, {
    "continue": "reason",
    "done": "respond"
})
graph.add_edge("respond", END)

agent = graph.compile()
```

### Enterprise Agentic Architecture (2026)

```
┌──────────────────────────────────────────────────────┐
│                 Application Layer                      │
│  [Chat UI]  [Code Assistant]  [Support Bot]            │
├──────────────────────────────────────────────────────┤
│              Orchestration Layer                        │
│  [Agent Router] [Workflow Engine] [State Management]   │
├──────────────────────────────────────────────────────┤
│              Model Gateway                              │
│  [Rate Limits] [Cost Controls] [Model Routing]         │
│  [Guardrails] [Input/Output Validation]                │
├──────────────────────────────────────────────────────┤
│              Inference Layer                            │
│  [vLLM]  [llm-d]  [KServe on OpenShift]               │
├──────────────────────────────────────────────────────┤
│              Observability Layer                        │
│  [Tracing] [Metrics] [Audit Logs] [Cost Tracking]     │
└──────────────────────────────────────────────────────┘
```

### Governance (Critical for Enterprise)

In enterprise AI, you cannot just let agents do anything. You need:
- **Guardrails**: rules that block harmful or off-topic outputs
- **Human-in-the-loop**: approval gates for high-risk actions
- **Audit trail**: record every agent decision for compliance
- **Cost controls**: prevent runaway API costs
- **Tool permissions**: agents can only access authorized tools

---

## 10. Kubernetes for AI Workloads

You already know Kubernetes well. Here is what is different for AI.

### GPU Scheduling

```yaml
resources:
  limits:
    nvidia.com/gpu: "1"    # request 1 GPU
  requests:
    nvidia.com/gpu: "1"    # must match limits for GPU
```

Key differences from CPU workloads:
- GPUs cannot be shared between pods (1 GPU = 1 pod, unless using MIG/MPS)
- GPU memory is not overcommittable
- Scheduling is harder (fewer GPUs than CPUs)
- Node affinity matters (different GPU types: A100, H100, MI300X)

### Key Kubernetes Concepts for AI

| Concept | Why It Matters for AI |
|---------|---------------------|
| **KServe** | CRD for model serving (InferenceService) |
| **Inference Gateway** | K8s Gateway API extension for AI routing |
| **LeaderWorkerSet (LWS)** | For multi-node distributed inference |
| **KEDA** | Event-driven autoscaling (scale on queue depth) |
| **Node Feature Discovery** | Auto-detect GPU types on nodes |
| **NVIDIA GPU Operator** | Manages GPU drivers and runtime on K8s |

### Distributed Inference on K8s

When a model is too big for one GPU:

```
                    [Inference Gateway]
                          │
              ┌───────────┼───────────┐
              ▼           ▼           ▼
         [Pod 1]     [Pod 2]     [Pod 3]
         GPU: A100   GPU: A100   GPU: A100
         Layers 1-10 Layers 11-20 Layers 21-32

         ←── Tensor Parallelism (split within layers) ──→
         ←── Pipeline Parallelism (split across layers) ──→
```

---

## 11. Putting It All Together

Here is how all the pieces connect for this role:

```
A user asks a question to Red Hat's AI product
      │
      ▼
[Agentic AI Layer]  -- YOU BUILD THIS
   Agent decides it needs to:
   1. Search a knowledge base (MCP tool call)
   2. Generate code (LLM call)
   3. Review the code (reflection pattern)
      │
      ▼
[Model Gateway]  -- YOU HELP BUILD THIS
   Routes to the right model (cost vs quality)
   Enforces guardrails and rate limits
      │
      ▼
[llm-d on OpenShift]  -- YOU DEPLOY AND OPTIMIZE THIS
   KV-cache-aware routing
   Disaggregated prefill/decode
      │
      ▼
[vLLM on GPU Nodes]  -- YOU UNDERSTAND AND TUNE THIS
   PagedAttention, speculative decoding
   Quantized models for efficiency
      │
      ▼
Response flows back through the stack
```

---

## 12. Interview Prep Checklist

### Must Be Able to Explain

- [ ] How a Transformer works (attention, tokens, embeddings)
- [ ] What KV cache is and why PagedAttention matters
- [ ] How quantization works and the trade-offs (quality vs speed vs memory)
- [ ] What speculative decoding is and when to use it
- [ ] How vLLM serves models (architecture, continuous batching)
- [ ] What llm-d adds on top of vLLM (disaggregated serving, KV-cache routing)
- [ ] How KServe works on OpenShift (InferenceService CRD, deployment modes)
- [ ] The 4 agentic patterns (tool use, planning, reflection, multi-agent)
- [ ] What MCP is and how agents use tools
- [ ] How to build an agent with LangGraph
- [ ] GPU scheduling on Kubernetes
- [ ] Enterprise AI governance (guardrails, HITL, audit)

### Must Be Able to Code

- [ ] Write a PyTorch training loop from scratch
- [ ] Load and run a Hugging Face model
- [ ] Serve a model with vLLM and query it
- [ ] Build a simple LangGraph agent with tool use
- [ ] Write a KServe InferenceService YAML
- [ ] Write a FastAPI endpoint that calls an LLM

### Must Be Able to Discuss

- [ ] "How would you deploy a 70B model across 4 GPUs?"
- [ ] "How would you reduce inference cost by 50%?"
- [ ] "Design an agentic system for automated code review"
- [ ] "How would you add guardrails to prevent an agent from accessing unauthorized data?"
- [ ] "What happens when an LLM serving pod gets OOMKilled?"
- [ ] "How would you evaluate whether an agent is performing well?"

---

## 13. Hands-On Projects

Do these in order. Each builds on the previous one.

### Project 1: Serve a Model with vLLM (2-3 hours)

```bash
pip install vllm
vllm serve Qwen/Qwen2.5-1.5B-Instruct --dtype float16
# Test it with curl
```

**What you learn:** vLLM basics, OpenAI-compatible API, model loading.

### Project 2: PyTorch Fine-Tuning (4-6 hours)

Fine-tune a small model with LoRA using Hugging Face:

```python
from transformers import AutoModelForCausalLM, TrainingArguments
from peft import LoraConfig, get_peft_model
from trl import SFTTrainer

# Load base model
model = AutoModelForCausalLM.from_pretrained("Qwen/Qwen2.5-1.5B-Instruct")

# Add LoRA adapters (only train ~1% of parameters)
lora_config = LoraConfig(r=16, lora_alpha=32, target_modules=["q_proj", "v_proj"])
model = get_peft_model(model, lora_config)

# Train on your data
trainer = SFTTrainer(model=model, train_dataset=dataset, args=training_args)
trainer.train()
```

**What you learn:** PyTorch training, LoRA, Hugging Face ecosystem.

### Project 3: Build an Agent with LangGraph (4-6 hours)

Build an agent that can search the web and write code.

**What you learn:** Agentic patterns, tool use, state management.

### Project 4: Deploy on Kubernetes with KServe (4-6 hours)

Deploy your vLLM model on a K8s cluster using KServe InferenceService.

**What you learn:** KServe, GPU scheduling, production deployment.

### Project 5: Build a Proof-of-Concept (Weekend Project)

Combine everything: an agentic AI app that uses LangGraph for orchestration, vLLM for inference, deployed on OpenShift with KServe.

**This is your interview killer. Mention it in the conversation.**

---

## 14. Resources

### Official Documentation
- vLLM: https://docs.vllm.ai
- llm-d: https://github.com/llm-d/llm-d
- KServe: https://kserve.github.io/website/
- LangGraph: https://langchain-ai.github.io/langgraph/
- PyTorch: https://pytorch.org/tutorials/
- Red Hat OpenShift AI: https://docs.redhat.com/en/documentation/red_hat_openshift_ai_self-managed/

### Courses (Priority Order)
1. **PyTorch in 60 Minutes** (free): https://pytorch.org/tutorials/beginner/deep_learning_60min_blitz.html
2. **Hugging Face NLP Course** (free): https://huggingface.co/learn/nlp-course
3. Your existing O'Reilly certs (LLM Agents with LangGraph, AI Agents with MCP)

### Key Blog Posts
- vLLM Model Runner V2 (2026): https://vllm.ai/blog/2026-03-24-mrv2
- llm-d on Red Hat Developer: https://developers.redhat.com/articles/2025/05/20/llm-d-kubernetes-native-distributed-inferencing
- Agentic AI Architecture Patterns 2026: https://vdf.ai/blog/enterprise-ai-agent-platform-architecture-patterns-2026/

### Papers (If You Want to Go Deeper)
- "Efficient Memory Management for Large Language Model Serving with PagedAttention" (the vLLM paper)
- "SpecInfer: Accelerating LLM Serving with Tree-based Speculative Inference"

---

*Last updated: July 2026. Good luck -- you have a stronger foundation than most candidates already.*
