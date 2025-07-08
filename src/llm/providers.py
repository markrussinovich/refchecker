"""
LLM provider implementations for reference extraction
"""

import json
import os
from typing import List, Dict, Any, Optional
import logging

from .base import LLMProvider

logger = logging.getLogger(__name__)



class LLMProviderMixin:
    """Common functionality for all LLM providers"""
    
    def _create_extraction_prompt(self, bibliography_text: str) -> str:
        """Create prompt for reference extraction"""
        return f"""
Please extract individual references from the following bibliography text. Each reference should be a complete bibliographic entry.

Instructions:
1. Split the bibliography into individual references
2. Each reference should include authors, title, publication venue, year, and any URLs/DOIs
3. Place a hashmark (#) rather than period between fields of a reference
4. Return ONLY the references, one per line
5. Do not include reference numbers like [1], [2], etc.
6. Each reference should be on its own line
7. Do not add any additional text or explanations

Bibliography text:
{bibliography_text}
"""
    
    def _parse_llm_response(self, content: str) -> List[str]:
        """Parse LLM response into list of references"""
        if not content:
            return []
        
        # Ensure content is a string
        if not isinstance(content, str):
            content = str(content)
        
        # Clean the content - remove leading/trailing whitespace
        content = content.strip()
        
        # Split by double newlines first to handle paragraph-style formatting
        # then fall back to single newlines
        references = []
        
        # Try double newline splitting first (paragraph style)
        if '\n\n' in content:
            potential_refs = content.split('\n\n')
        else:
            # Fall back to single newline splitting
            potential_refs = content.split('\n')
        
        for ref in potential_refs:
            ref = ref.strip()
            
            # Skip empty lines, headers, and explanatory text
            if not ref:
                continue
            if ref.lower().startswith(('reference', 'here are', 'below are', 'extracted', 'bibliography')):
                continue
            if ref.startswith('#'):
                continue
            if 'extracted from the bibliography' in ref.lower():
                continue
            if 'formatted as a complete' in ref.lower():
                continue
            
            # Remove common prefixes (bullets, numbers, etc.)
            ref = ref.lstrip('- *•')
            ref = ref.strip()
            
            # Remove reference numbers like "1.", "[1]", "(1)" from the beginning
            import re
            ref = re.sub(r'^(\d+\.|\[\d+\]|\(\d+\))\s*', '', ref)
            
            # Filter out very short lines (likely not complete references)
            if len(ref) > 30:  # Increased minimum length for academic references
                references.append(ref)
        
        return references


class OpenAIProvider(LLMProvider, LLMProviderMixin):
    """OpenAI GPT provider for reference extraction"""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.api_key = config.get("api_key") or os.getenv("REFCHECKER_OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")
        self.client = None
        
        if self.api_key:
            try:
                import openai
                self.client = openai.OpenAI(api_key=self.api_key)
            except ImportError:
                logger.error("OpenAI library not installed. Install with: pip install openai")
    
    def is_available(self) -> bool:
        return self.client is not None and self.api_key is not None
    
    def extract_references(self, bibliography_text: str) -> List[str]:
        if not self.is_available():
            raise Exception("OpenAI provider not available")
        
        prompt = self._create_extraction_prompt(bibliography_text)
        
        try:
            response = self.client.chat.completions.create(
                model=self.model or "gpt-4o-mini",
                messages=[
                    {"role": "user", "content": prompt}
                ],
                max_tokens=self.max_tokens,
                temperature=self.temperature
            )
            
            content = response.choices[0].message.content
            return self._parse_llm_response(content)
            
        except Exception as e:
            logger.error(f"OpenAI API call failed: {e}")
            raise


class AnthropicProvider(LLMProvider, LLMProviderMixin):
    """Anthropic Claude provider for reference extraction"""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.api_key = config.get("api_key") or os.getenv("REFCHECKER_ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_API_KEY")
        self.client = None
        
        if self.api_key:
            try:
                import anthropic
                self.client = anthropic.Anthropic(api_key=self.api_key)
            except ImportError:
                logger.error("Anthropic library not installed. Install with: pip install anthropic")
    
    def is_available(self) -> bool:
        return self.client is not None and self.api_key is not None
    
    def extract_references(self, bibliography_text: str) -> List[str]:
        if not self.is_available():
            raise Exception("Anthropic provider not available")
        
        prompt = self._create_extraction_prompt(bibliography_text)
        
        try:
            response = self.client.messages.create(
                model=self.model or "claude-3-haiku-20240307",
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )
            
            logger.debug(f"Anthropic response type: {type(response.content)}")
            logger.debug(f"Anthropic response content: {response.content}")
            
            # Handle different response formats
            if hasattr(response.content[0], 'text'):
                content = response.content[0].text
            elif isinstance(response.content[0], dict) and 'text' in response.content[0]:
                content = response.content[0]['text']
            elif hasattr(response.content[0], 'content'):
                content = response.content[0].content
            else:
                content = str(response.content[0])
            
            # Ensure content is a string
            if not isinstance(content, str):
                content = str(content)
            
            return self._parse_llm_response(content)
            
        except Exception as e:
            logger.error(f"Anthropic API call failed: {e}")
            raise


class GoogleProvider(LLMProvider, LLMProviderMixin):
    """Google Gemini provider for reference extraction"""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.api_key = config.get("api_key") or os.getenv("REFCHECKER_GOOGLE_API_KEY") or os.getenv("GOOGLE_API_KEY")
        self.client = None
        
        if self.api_key:
            try:
                import google.generativeai as genai
                genai.configure(api_key=self.api_key)
                self.client = genai.GenerativeModel(self.model or "gemini-1.5-flash")
            except ImportError:
                logger.error("Google Generative AI library not installed. Install with: pip install google-generativeai")
    
    def is_available(self) -> bool:
        return self.client is not None and self.api_key is not None
    
    def extract_references(self, bibliography_text: str) -> List[str]:
        if not self.is_available():
            raise Exception("Google provider not available")
        
        prompt = self._create_extraction_prompt(bibliography_text)
        
        try:
            response = self.client.generate_content(
                prompt,
                generation_config={
                    "max_output_tokens": self.max_tokens,
                    "temperature": self.temperature,
                }
            )
            
            content = response.text
            return self._parse_llm_response(content)
            
        except Exception as e:
            logger.error(f"Google API call failed: {e}")
            raise


class AzureProvider(LLMProvider, LLMProviderMixin):
    """Azure OpenAI provider for reference extraction"""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.api_key = config.get("api_key") or os.getenv("REFCHECKER_AZURE_API_KEY") or os.getenv("AZURE_OPENAI_API_KEY")
        self.endpoint = config.get("endpoint") or os.getenv("REFCHECKER_AZURE_ENDPOINT") or os.getenv("AZURE_OPENAI_ENDPOINT")
        self.client = None
        
        logger.debug(f"Azure provider initialized - API key present: {self.api_key is not None}, Endpoint present: {self.endpoint is not None}")
        
        if self.api_key and self.endpoint:
            try:
                import openai
                self.client = openai.AzureOpenAI(
                    api_key=self.api_key,
                    api_version="2024-02-01",
                    azure_endpoint=self.endpoint
                )
                logger.debug("Azure OpenAI client created successfully")
            except ImportError:
                logger.error("OpenAI library not installed. Install with: pip install openai")
        else:
            logger.warning(f"Azure provider not available - missing {'API key' if not self.api_key else 'endpoint'}")
    
    def is_available(self) -> bool:
        available = self.client is not None and self.api_key is not None and self.endpoint is not None
        if not available:
            logger.debug(f"Azure provider not available: client={self.client is not None}, api_key={self.api_key is not None}, endpoint={self.endpoint is not None}")
        return available
    
    def extract_references(self, bibliography_text: str) -> List[str]:
        if not self.is_available():
            raise Exception("Azure provider not available")
        
        prompt = self._create_extraction_prompt(bibliography_text)
        
        try:
            response = self.client.chat.completions.create(
                model=self.model or "gpt-4o",
                messages=[
                    {"role": "user", "content": prompt}
                ],
                max_tokens=self.max_tokens,
                temperature=self.temperature
            )
            
            content = response.choices[0].message.content
            return self._parse_llm_response(content)
            
        except Exception as e:
            logger.error(f"Azure API call failed: {e}")
            raise

class vLLMProvider(LLMProvider, LLMProviderMixin):
    """vLLM provider using OpenAI-compatible server mode for local Hugging Face models"""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.model_name = config.get("model") or "microsoft/DialoGPT-medium"
        self.server_url = config.get("server_url") or os.getenv("REFCHECKER_VLLM_SERVER_URL") or "http://localhost:8000"
        self.auto_start_server = config.get("auto_start_server", os.getenv("REFCHECKER_VLLM_AUTO_START", "true").lower() == "true")
        self.server_timeout = config.get("server_timeout", int(os.getenv("REFCHECKER_VLLM_TIMEOUT", "300")))
        
        # Allow skipping initialization for testing
        self.skip_initialization = config.get("skip_initialization", False)
        
        self.client = None
        self.server_process = None
        
        logger.info(f"vLLM provider initialized - Server URL: {self.server_url}, Model: {self.model_name}, Auto start: {self.auto_start_server}")
        
        # Only initialize if not skipping
        if not self.skip_initialization:
            # Clean debugger environment variables early
            self._clean_debugger_environment()
            
            if self.auto_start_server:
                self._ensure_server_running()
            
            try:
                import openai
                # vLLM provides OpenAI-compatible API
                self.client = openai.OpenAI(
                    api_key="EMPTY",  # vLLM doesn't require API key
                    base_url=f"{self.server_url}/v1"
                )
                logger.info("OpenAI client configured for vLLM server")
            except ImportError:
                logger.error("OpenAI library not installed. Install with: pip install openai")
    
    def _clean_debugger_environment(self):
        """Clean debugger environment variables that interfere with vLLM"""
        debugger_vars = [
            'DEBUGPY_LAUNCHER_PORT',
            'PYDEVD_LOAD_VALUES_ASYNC', 
            'PYDEVD_USE_FRAME_EVAL',
            'PYDEVD_WARN_SLOW_RESOLVE_TIMEOUT'
        ]
        
        for var in debugger_vars:
            if var in os.environ:
                logger.debug(f"Removing debugger variable: {var}")
                del os.environ[var]
        
        # Clean PYTHONPATH of debugger modules
        if 'PYTHONPATH' in os.environ:
            pythonpath_parts = os.environ['PYTHONPATH'].split(':')
            clean_pythonpath = [p for p in pythonpath_parts if 'debugpy' not in p and 'pydevd' not in p]
            if clean_pythonpath != pythonpath_parts:
                logger.debug("Cleaned PYTHONPATH of debugger modules")
                os.environ['PYTHONPATH'] = ':'.join(clean_pythonpath)

    def _get_optimal_tensor_parallel_size(self):
        """Determine optimal tensor parallel size based on available GPUs"""
        try:
            import torch
            
            available_gpus = torch.cuda.device_count() if torch.cuda.is_available() else 1
            
            if available_gpus <= 1:
                return 1
            
            # For most models, use up to 4 GPUs for stability
            return min(available_gpus, 4)
        
        except Exception as e:
            logger.debug(f"Error determining tensor parallel size: {e}, defaulting to 1")
            return 1
    
    def _kill_existing_server(self):
        """Kill any existing vLLM server processes"""
        try:
            import subprocess
            subprocess.run(["pkill", "-f", "vllm"], timeout=10, capture_output=True)
            import time
            time.sleep(2)  # Wait for cleanup
        except Exception as e:
            logger.debug(f"Error killing existing server: {e}")
    
    def _is_debugger_environment(self):
        """Check if running in a debugger environment"""
        debugger_indicators = [
            'DEBUGPY_LAUNCHER_PORT',
            'PYDEVD_LOAD_VALUES_ASYNC',
            'PYDEVD_USE_FRAME_EVAL'
        ]
        return any(var in os.environ for var in debugger_indicators)
    
    def _start_server(self):
        """Start vLLM server with optimal configuration"""
        try:
            import subprocess
            import torch
            
            # Kill any existing server
            self._kill_existing_server()
            
            # Determine optimal tensor parallel size
            tensor_parallel_size = self._get_optimal_tensor_parallel_size()
            
            # Check if we're in a debugger environment
            if self._is_debugger_environment():
                logger.info("Debugger environment detected, using standalone server launcher")
                return self._start_server_standalone(tensor_parallel_size)
            else:
                return self._start_server_direct(tensor_parallel_size)
            
        except Exception as e:
            logger.error(f"Failed to start vLLM server: {e}")
            return False
    
    def _start_server_standalone(self, tensor_parallel_size):
        """Start server using standalone script to avoid debugger conflicts"""
        import subprocess
        import torch
        
        # Path to standalone launcher script
        script_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 
                                  "..", "scripts", "start_vllm_server.py")
        
        # Build command for standalone launcher
        cmd = [
            "python", script_path,
            "--model", self.model_name,
            "--port", "8000",
            "--tensor-parallel-size", str(tensor_parallel_size),
            "--daemon"
        ]
        
        # Add memory optimization for smaller GPUs
        if torch.cuda.is_available():
            gpu_memory = torch.cuda.get_device_properties(0).total_memory / (1024**3)  # GB
            if gpu_memory < 40:  # Less than 40GB VRAM
                cmd.extend([
                    "--gpu-memory-util", "0.8",
                    "--max-model-len", "4096"
                ])
        
        logger.info(f"Starting vLLM server via standalone launcher: {' '.join(cmd)}")
        
        # Start the launcher (which will start the server as daemon)
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        
        if result.returncode == 0:
            logger.info("vLLM server launcher completed successfully")
            # The actual server process is running as daemon, we don't have direct handle
            self.server_process = None  # We don't manage the daemon directly
            return True
        else:
            logger.error(f"vLLM server launcher failed: {result.stderr}")
            return False
    
    def _start_server_direct(self, tensor_parallel_size):
        """Start server directly (for non-debugger environments)"""
        import subprocess
        import torch
        
        # Build command with chat template enabled
        cmd = [
            "python", "-m", "vllm.entrypoints.openai.api_server",
            "--model", self.model_name,
            "--host", "0.0.0.0",
            "--port", "8000",
            "--tensor-parallel-size", str(tensor_parallel_size),
            "--disable-log-requests"  # Reduce log spam
        ]
        
        # Add memory optimization for smaller GPUs
        if torch.cuda.is_available():
            gpu_memory = torch.cuda.get_device_properties(0).total_memory / (1024**3)  # GB
            if gpu_memory < 40:  # Less than 40GB VRAM
                cmd.extend([
                    "--gpu-memory-utilization", "0.8",
                    "--max-model-len", "4096"
                ])
            else:
                cmd.extend([
                    "--gpu-memory-utilization", "0.9",
                    "--max-model-len", "8192"
                ])
        
        logger.info(f"Starting vLLM server: {' '.join(cmd)}")
        
        # Create clean environment for vLLM server
        clean_env = os.environ.copy()
        
        # Remove VS Code debugger variables
        debugger_vars = [
            'DEBUGPY_LAUNCHER_PORT',
            'PYDEVD_LOAD_VALUES_ASYNC',
            'PYDEVD_USE_FRAME_EVAL',
        ]
        
        for var in debugger_vars:
            clean_env.pop(var, None)
        
        # Clean PYTHONPATH of debugger modules
        if 'PYTHONPATH' in clean_env:
            pythonpath_parts = clean_env['PYTHONPATH'].split(':')
            clean_pythonpath = [p for p in pythonpath_parts if 'debugpy' not in p and 'pydevd' not in p]
            if clean_pythonpath:
                clean_env['PYTHONPATH'] = ':'.join(clean_pythonpath)
            else:
                clean_env.pop('PYTHONPATH', None)
                
        # kill any existing server processes
        self._kill_existing_server()
        
        # Start the server process with clean environment
        self.server_process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=clean_env,
            start_new_session=True  # Start in new process group
        )
        
        return True
    
    def _wait_for_server(self, timeout=300):
        """Wait for vLLM server to be ready"""
        import time
        import requests
        
        start_time = time.time()
        
        logger.info(f"Waiting for vLLM server to start (timeout: {timeout}s)...")
        
        while (time.time() - start_time) < timeout:
            if self.server_process and self.server_process.poll() is not None:
                # Process has terminated
                stdout, stderr = self.server_process.communicate()
                logger.error(f"vLLM server terminated unexpectedly:")
                logger.error(f"STDOUT: {stdout}")
                logger.error(f"STDERR: {stderr}")
                return False
            
            try:
                # Check health endpoint
                response = requests.get(f"{self.server_url}/health", timeout=5)
                if response.status_code == 200:
                    logger.info("vLLM server health check passed")
                    
                    # Check models endpoint
                    response = requests.get(f"{self.server_url}/v1/models", timeout=5)
                    if response.status_code == 200:
                        models_data = response.json()
                        loaded_models = [model["id"] for model in models_data.get("data", [])]
                        logger.info(f"vLLM server is ready with models: {loaded_models}")
                        return True
                    
            except requests.exceptions.RequestException as e:
                logger.debug(f"Server not ready yet: {e}")
                pass
            
            elapsed = time.time() - start_time
            if elapsed % 30 == 0:  # Log every 30 seconds
                logger.info(f"Still waiting for server... ({elapsed:.0f}s elapsed)")
            
            time.sleep(2)
        
        logger.error(f"vLLM server failed to start within {timeout} seconds")
        return False
    
    def _ensure_server_running(self):
        """Ensure vLLM server is running, start if necessary"""
        # First check if server is already running
        if self._check_server_health():
            logger.info("vLLM server is already running and healthy")
            return True
        
        logger.info("Starting vLLM server...")
        
        # Try to start the server
        if self._start_server():
            if self._wait_for_server(self.server_timeout):
                return True
        
        # If we get here, server failed to start
        if self.server_process:
            logger.error("Server startup failed, cleaning up...")
            self._kill_existing_server()
            self.server_process = None
        
        return False
    
    def _check_server_health(self):
        """Check if vLLM server is healthy and has the correct model"""
        try:
            import requests
            
            # First check if server is responding
            response = requests.get(f"{self.server_url}/health", timeout=10)
            if response.status_code != 200:
                logger.debug(f"Health check failed: {response.status_code}")
                return False
            
            # Check if the correct model is loaded
            response = requests.get(f"{self.server_url}/v1/models", timeout=10)
            if response.status_code == 200:
                models_data = response.json()
                loaded_models = [model["id"] for model in models_data.get("data", [])]
                if self.model_name in loaded_models:
                    logger.debug(f"Correct model {self.model_name} is loaded")
                    return True
                else:
                    logger.info(f"Wrong model loaded. Expected: {self.model_name}, Found: {loaded_models}")
                    return False
            
            return False
            
        except requests.exceptions.RequestException as e:
            logger.debug(f"Server health check failed: {e}")
            return False
    
    def is_available(self) -> bool:
        """Check if vLLM server is available"""
        if not self.client:
            return False
        
        # Check server health
        if self._check_server_health():
            return True
        
        # If auto_start_server is enabled, try to start it
        if self.auto_start_server:
            logger.info("vLLM server not responding, attempting to restart...")
            return self._ensure_server_running()
        
        return False

    def _chunk_bibliography(self, bibliography_text: str, max_tokens: int = 2000) -> List[str]:
        """Split bibliography into chunks without cutting references in the middle, prioritizing natural boundaries"""
        
        # First, try to split by natural boundaries (newlines) and common reference patterns
        # Look for numbered references like [1], (1), 1., etc.
        import re
        
        # Split on common reference number patterns at the start of lines
        reference_patterns = [
            r'\n\s*\[\d+\]',  # [1], [2], etc.
            r'\n\s*\(\d+\)',  # (1), (2), etc. 
            r'\n\s*\d+\.',    # 1., 2., etc.
            r'\n\s*\d+\)',    # 1), 2), etc.
        ]
        
        # Try each pattern to find the best way to split
        potential_references = []
        for pattern in reference_patterns:
            splits = re.split(pattern, bibliography_text)
            if len(splits) > 1:
                # Reconstruct references with their numbers
                refs = []
                matches = re.findall(pattern, bibliography_text)
                
                if splits[0].strip():  # First part before any numbered reference
                    refs.append(splits[0].strip())
                
                for i, match in enumerate(matches):
                    if i + 1 < len(splits):
                        ref_text = match.strip() + splits[i + 1]
                        refs.append(ref_text.strip())
                
                if len(refs) > len(potential_references):
                    potential_references = refs
                break
        
        # If no clear reference pattern found, prioritize natural boundaries
        if not potential_references:
            # First try double newlines (paragraph breaks)
            paragraphs = [ref.strip() for ref in bibliography_text.split('\n\n') if ref.strip()]
            if len(paragraphs) > 1:
                potential_references = paragraphs
            else:
                # Then try single newlines as natural boundaries
                lines = [line.strip() for line in bibliography_text.split('\n') if line.strip()]
                if len(lines) > 1:
                    potential_references = lines
        
        # If still no good splits, split by single newlines but be more careful
        if len(potential_references) <= 1:
            lines = bibliography_text.split('\n')
            potential_references = []
            current_ref = ""
            
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                    
                # Check if this line starts a new reference (has typical reference indicators)
                if (re.match(r'^\[\d+\]|^\(\d+\)|^\d+\.|^\d+\)', line) or 
                    (current_ref and len(line) > 50 and any(indicator in line.lower() for indicator in ['journal', 'proceedings', 'conference', 'arxiv', 'doi']))):
                    if current_ref:
                        potential_references.append(current_ref.strip())
                    current_ref = line
                else:
                    current_ref += " " + line
            
            if current_ref:
                potential_references.append(current_ref.strip())
        
        # Now group references into chunks that fit within token limit
        chunks = []
        current_chunk = ""
        
        for ref in potential_references:
            # Rough estimate: 1 token ≈ 4 characters (conservative estimate)
            estimated_tokens = len(current_chunk + "\n" + ref) // 4
            
            if estimated_tokens > max_tokens and current_chunk:
                # Current chunk is getting too large, start a new one
                chunks.append(current_chunk.strip())
                current_chunk = ref
            else:
                if current_chunk:
                    current_chunk += "\n" + ref
                else:
                    current_chunk = ref
        
        if current_chunk:
            chunks.append(current_chunk.strip())
        
        # If we still have chunks that are too large, split them more aggressively
        # but still prioritize natural boundaries
        final_chunks = []
        for chunk in chunks:
            chunk_tokens = len(chunk) // 4
            if chunk_tokens > max_tokens:
                logger.warning(f"Chunk still too large ({chunk_tokens} tokens), splitting more aggressively")
                # First try splitting by newlines within the chunk
                lines = chunk.split('\n')
                if len(lines) > 1:
                    sub_chunk = ""
                    for line in lines:
                        test_chunk = sub_chunk + "\n" + line if sub_chunk else line
                        if len(test_chunk) // 4 > max_tokens and sub_chunk:
                            final_chunks.append(sub_chunk.strip())
                            sub_chunk = line
                        else:
                            sub_chunk = test_chunk
                    
                    if sub_chunk:
                        final_chunks.append(sub_chunk.strip())
                else:
                    # Only as last resort, split by sentences or semicolons
                    sentences = re.split(r'[.;]\s+', chunk)
                    sub_chunk = ""
                    
                    for sentence in sentences:
                        test_chunk = sub_chunk + sentence + ". " if sub_chunk else sentence
                        if len(test_chunk) // 4 > max_tokens and sub_chunk:
                            final_chunks.append(sub_chunk.strip())
                            sub_chunk = sentence + ". "
                        else:
                            sub_chunk = test_chunk
                    
                    if sub_chunk:
                        final_chunks.append(sub_chunk.strip())
            else:
                final_chunks.append(chunk)
        
        logger.info(f"Split bibliography into {len(final_chunks)} chunks (max {max_tokens} tokens each)")
        return final_chunks

    def extract_references(self, bibliography_text: str) -> List[str]:
        """Extract references using vLLM server (OpenAI-compatible API)"""
        if not self.is_available():
            raise Exception("vLLM server not available. Make sure vLLM server is running.")
        
        # Get model's max_tokens from configuration
        from src.utils.config_validator import get_config
        config = get_config()
        model_max_tokens = config.get('llm_providers', {}).get('vllm', {}).get('max_tokens', 4000)
        
        # Check if bibliography is too long and needs chunking
        estimated_tokens = len(bibliography_text) // 4  # Rough estimate
        
        # Account for prompt overhead - server mode handles chat templates automatically
        prompt_overhead = 300  # Conservative estimate for prompt template and system messages
        # Ensure prompt is < 1/2 the model's total token limit
        max_input_tokens = (model_max_tokens // 2) - prompt_overhead
        
        logger.info(f"Using model max_tokens: {model_max_tokens}, max_input_tokens: {max_input_tokens}")
        
        if estimated_tokens > max_input_tokens:
            logger.info(f"Bibliography too long ({estimated_tokens} estimated tokens), splitting into chunks")
            chunks = self._chunk_bibliography(bibliography_text, max_input_tokens)
            
            all_references = []
            for i, chunk in enumerate(chunks):
                logger.info(f"Processing chunk {i+1}/{len(chunks)}")
                prompt = self._create_extraction_prompt(chunk)
                
                chunk_references = self._extract_references_from_server(prompt)
                all_references.extend(chunk_references)
            
            # Remove duplicates while preserving order
            seen = set()
            unique_references = []
            for ref in all_references:
                ref_normalized = ref.strip().lower()
                if ref_normalized not in seen:
                    seen.add(ref_normalized)
                    unique_references.append(ref)
            
            logger.info(f"Extracted {len(unique_references)} unique references from {len(chunks)} chunks")
            return unique_references
        else:
            # Process normally for short bibliographies
            prompt = self._create_extraction_prompt(bibliography_text)
            return self._extract_references_from_server(prompt)
    
    def _extract_references_from_server(self, prompt: str) -> List[str]:
        """Extract references using vLLM server API"""
        try:
            logger.debug(f"Sending prompt to vLLM server (length: {len(prompt)})")
            
            # Use chat completions API - vLLM will automatically apply chat templates
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "user", "content": prompt}
                ],
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                stop=None  # Let the model use its default stop tokens
            )
            
            content = response.choices[0].message.content
            
            logger.debug(f"Received response from vLLM server:")
            logger.debug(f"  Length: {len(content)}")
            logger.debug(f"  First 200 chars: {content[:200]}...")
            logger.debug(f"  Finish reason: {response.choices[0].finish_reason}")
            
            return self._parse_llm_response(content)
            
        except Exception as e:
            logger.error(f"vLLM server API call failed: {e}")
            raise

    def test_server_response(self):
        """Test method to verify server is responding correctly"""
        if not self.is_available():
            print("Server not available")
            return
            
        test_prompt = "What is 2+2? Answer briefly."
        
        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "user", "content": test_prompt}
                ],
                max_tokens=50,
                temperature=0.1
            )
            
            content = response.choices[0].message.content
            print(f"Test successful!")
            print(f"Prompt: {test_prompt}")
            print(f"Response: {content}")
            print(f"Finish reason: {response.choices[0].finish_reason}")
            
        except Exception as e:
            print(f"Test failed: {e}")
    
    def cleanup(self):
        """Cleanup vLLM server resources"""
        if self.server_process:
            logger.info("Shutting down vLLM server...")
            try:
                self.server_process.terminate()
                self._kill_existing_server()
            except Exception as e:
                logger.error(f"Error during vLLM server cleanup: {e}")
            finally:
                self.server_process = None
    
    def __del__(self):
        """Cleanup on deletion"""
        self.cleanup()
