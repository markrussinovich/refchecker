"""
LLM provider implementations for reference extraction
"""

import json
import os
import subprocess
from typing import List, Dict, Any, Optional
import logging

from .base import LLMProvider

logger = logging.getLogger(__name__)



class LLMProviderMixin:
    """Common functionality for all LLM providers"""
    
    def _clean_bibtex_for_llm(self, bibliography_text: str) -> str:
        """Clean BibTeX text before sending to LLM to remove formatting artifacts"""
        if not bibliography_text:
            return bibliography_text
            
        import re
        
        # First, protect LaTeX commands from being stripped
        protected_commands = []
        command_pattern = r'\{\\[a-zA-Z]+(?:\s+[^{}]*?)?\}'
        
        def protect_command(match):
            protected_commands.append(match.group(0))
            return f"__PROTECTED_LATEX_{len(protected_commands)-1}__"
        
        text = re.sub(command_pattern, protect_command, bibliography_text)
        
        # Clean up LaTeX math expressions in titles (but preserve the math content)
        # Convert $expression$ to expression and ${expression}$ to expression
        text = re.sub(r'\$\{([^{}]+)\}\$', r'\1', text)  # ${expr}$ -> expr
        text = re.sub(r'\$([^$]+)\$', r'\1', text)        # $expr$ -> expr
        
        # Remove curly braces around titles and other fields
        # Match { content } where content doesn't contain unmatched braces
        text = re.sub(r'\{([^{}]+)\}', r'\1', text)
        
        # Clean up DOI and URL field contamination
        # Fix cases where DOI field contains both DOI and URL separated by *
        # Pattern: DOI*URL -> separate them properly
        text = re.sub(r'(doi\s*=\s*\{?)([^}*,]+)\*http([^},\s]*)\}?', r'\1\2},\n  url = {http\3}', text)
        text = re.sub(r'(\d+\.\d+/[^*\s,]+)\*http', r'\1,\n  url = {http', text)
        
        # Clean up asterisk contamination in DOI values within the text
        text = re.sub(r'(10\.[0-9]+/[A-Za-z0-9\-.:()/_]+)\*http', r'\1', text)
        
        # Restore protected LaTeX commands
        for i, command in enumerate(protected_commands):
            text = text.replace(f"__PROTECTED_LATEX_{i}__", command)
        
        return text

    def _create_extraction_prompt(self, bibliography_text: str) -> str:
        """Create prompt for reference extraction"""
        # Clean BibTeX formatting before sending to LLM
        cleaned_bibliography = self._clean_bibtex_for_llm(bibliography_text)
        
        return f"""
Please extract individual references from the following bibliography text. Each reference should be a complete bibliographic entry.

Instructions:
1. Split the bibliography into individual references based on numbered markers like [1], [2], etc.
2. IMPORTANT: References may span multiple lines. A single reference includes everything from one number marker (e.g., [37]) until the next number marker (e.g., [38])
3. For each reference, extract: authors, title, publication venue, year, and any URLs/DOIs
   - For BibTeX entries, extract fields correctly:
     * title = the actual paper title from "title" field
     * venue = from "journal", "booktitle", "conference" fields  
     * Do NOT confuse journal names like "arXiv preprint arXiv:1234.5678" with paper titles
4. Include references that are incomplete, like only author names and titles, but ignore ones that are just a URL without other details
5. Place a hashmark (#) rather than period between fields of a reference, but asterisks (*) between individual authors
   e.g. Author1*Author2*Author3#Title#Venue#Year#URL
6. CRITICAL: When extracting authors, understand BibTeX author field format correctly
   - In BibTeX, the "author" field contains author names separated by " and " (not commas)
   - Individual author names may be in "Last, First" format (e.g., "Smith, John")
   - Multiple authors are separated by " and " (e.g., "Smith, John and Doe, Jane")
   - SPECIAL CASE for collaborations: Handle "Last, First and others" pattern correctly
     * author = {"Khachatryan, Vardan and others"} → ONE explicit author plus et al: "Vardan Khachatryan*et al"
     * author = {"Smith, John and others"} → ONE explicit author plus et al: "John Smith*et al"
     * The "Last, First and others" pattern indicates a collaboration paper where only the first author is listed explicitly
   - EXAMPLES:
     * author = {"Dolan, Brian P."} → ONE author: "Dolan, Brian P."
     * author = {"Smith, John and Doe, Jane"} → TWO authors: "Smith, John*Doe, Jane"
     * author = {"Arnab, Anurag and Dehghani, Mostafa and Heigold, Georg"} → THREE authors: "Arnab, Anurag*Dehghani, Mostafa*Heigold, Georg"
     * author = {"Khachatryan, Vardan and others"} → ONE explicit author plus et al: "Vardan Khachatryan*et al"
   - Use asterisks (*) to separate individual authors in your output
   - For "Last, First" format, convert to "First Last" for readability (e.g., "Smith, John" → "John Smith")
   - If a BibTeX entry has NO author field, output an empty author field (nothing before the first #)
   - Do NOT infer or guess authors based on title or context - only use what is explicitly stated
7. CRITICAL: When extracting authors, preserve "et al" and similar indicators exactly as they appear
   - If the original says "John Smith, Jane Doe, et al" then output "John Smith, Jane Doe, et al"
   - If the original says "John Smith et al." then output "John Smith et al."
   - Also preserve variations like "and others", "etc.", "..." when used to indicate additional authors
   - Do NOT expand "et al" into individual author names, even if you know them
8. Return ONLY the references, one per line
9. Do not include reference numbers like [1], [2], etc. in your output
10. Do not add any additional text or explanations
11. Ensure that URLs and DOIs are from the specific reference only
    - When extracting URLs, preserve the complete URL including protocol
    - For BibTeX howpublished fields, extract the full URL from the field value
12. When parsing multi-line references, combine all authors from all lines before the title
13. CRITICAL: If the text contains no valid bibliographic references (e.g., only figures, appendix material, or explanatory text), simply return nothing - do NOT explain why you cannot extract references

Bibliography text:
{cleaned_bibliography}
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
            # Skip verbose LLM explanatory responses
            if 'cannot extract' in ref.lower() and ('references' in ref.lower() or 'bibliographic' in ref.lower()):
                continue
            if 'appears to be from' in ref.lower() and 'appendix' in ref.lower():
                continue
            if 'no numbered reference markers' in ref.lower():
                continue
            if 'only figures' in ref.lower() and 'learning curves' in ref.lower():
                continue
            if ref.lower().startswith('i cannot'):
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
        return self.extract_references_with_chunking(bibliography_text)
    
    def _create_extraction_prompt(self, bibliography_text: str) -> str:
        """Create prompt for reference extraction"""
        return LLMProviderMixin._create_extraction_prompt(self, bibliography_text)
    
    def _call_llm(self, prompt: str) -> str:
        """Make the actual OpenAI API call and return the response text"""
        try:
            response = self.client.chat.completions.create(
                model=self.model or "gpt-4.1",
                messages=[
                    {"role": "user", "content": prompt}
                ],
                max_tokens=self.max_tokens,
                temperature=self.temperature
            )
            
            return response.choices[0].message.content or ""
            
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
        return self.extract_references_with_chunking(bibliography_text)
    
    def _create_extraction_prompt(self, bibliography_text: str) -> str:
        """Create prompt for reference extraction"""
        return LLMProviderMixin._create_extraction_prompt(self, bibliography_text)
    
    def _call_llm(self, prompt: str) -> str:
        """Make the actual Anthropic API call and return the response text"""
        try:
            response = self.client.messages.create(
                model=self.model or "claude-sonnet-4-20250514",
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
            
            return content
            
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
        return self.extract_references_with_chunking(bibliography_text)
    
    def _create_extraction_prompt(self, bibliography_text: str) -> str:
        """Create prompt for reference extraction"""
        return LLMProviderMixin._create_extraction_prompt(self, bibliography_text)
    
    def _call_llm(self, prompt: str) -> str:
        """Make the actual Google API call and return the response text"""
        try:
            response = self.client.generate_content(
                prompt,
                generation_config={
                    "max_output_tokens": self.max_tokens,
                    "temperature": self.temperature,
                }
            )
            
            return response.text or ""
            
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
        return self.extract_references_with_chunking(bibliography_text)
    
    def _create_extraction_prompt(self, bibliography_text: str) -> str:
        """Create prompt for reference extraction"""
        return LLMProviderMixin._create_extraction_prompt(self, bibliography_text)
    
    def _call_llm(self, prompt: str) -> str:
        """Make the actual Azure OpenAI API call and return the response text"""
        try:
            response = self.client.chat.completions.create(
                model=self.model or "gpt-4o",
                messages=[
                    {"role": "user", "content": prompt}
                ],
                max_tokens=self.max_tokens,
                temperature=self.temperature
            )
            
            return response.choices[0].message.content or ""
            
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
                if self._ensure_server_running() == False:
                    logger.error("Failed to start vLLM server, provider will not be available")
                    # this is a fatal error that shouldn't create the object
                    raise Exception("vLLM server failed to start")
            
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
            # Use a more specific pattern to only kill vLLM server processes, not any process containing "vllm"
            subprocess.run(["pkill", "-f", "vllm.entrypoints.openai.api_server"], timeout=10, capture_output=True)
            import time
            time.sleep(2)  # Wait for cleanup
        except Exception as e:
            logger.debug(f"Error killing existing server: {e}")
    
    def _start_server(self):
        """Start vLLM server using standalone launcher"""
        try:
            import subprocess
            import torch
            
            # Kill any existing server
            self._kill_existing_server()
            
            # Determine optimal tensor parallel size
            tensor_parallel_size = self._get_optimal_tensor_parallel_size()
            
            # Always use standalone server launcher for reliability
            return self._start_server_standalone(tensor_parallel_size)
            
        except Exception as e:
            logger.error(f"Failed to start vLLM server: {e}")
            return False
    
    def _find_vllm_launcher_script(self):
        """Find the vLLM launcher script, supporting both development and PyPI installs"""
        import pkg_resources
        
        # First try to find it as a package resource (for PyPI installs)
        try:
            script_path = pkg_resources.resource_filename('refchecker', 'scripts/start_vllm_server.py')
            if os.path.exists(script_path):
                logger.debug(f"Found vLLM launcher script via pkg_resources: {script_path}")
                return script_path
        except Exception as e:
            logger.debug(f"Could not find script via pkg_resources: {e}")
        
        # Try relative path for development installs
        current_dir = os.path.dirname(os.path.dirname(__file__))  # src/llm -> src
        project_root = os.path.dirname(current_dir)  # src -> project root
        script_path = os.path.join(project_root, "scripts", "start_vllm_server.py")
        
        if os.path.exists(script_path):
            logger.debug(f"Found vLLM launcher script via relative path: {script_path}")
            return script_path
        
        # Try looking in the same directory structure as this file (for src-based installs)
        src_dir = os.path.dirname(os.path.dirname(__file__))  # src/llm -> src
        script_path = os.path.join(src_dir, "scripts", "start_vllm_server.py")
        
        if os.path.exists(script_path):
            logger.debug(f"Found vLLM launcher script in src directory: {script_path}")
            return script_path
        
        # If all else fails, try to create a temporary script
        logger.warning("Could not find standalone vLLM launcher script, creating temporary one")
        return self._create_temporary_launcher_script()
    
    def _create_temporary_launcher_script(self):
        """Create a temporary launcher script if the packaged one cannot be found"""
        import tempfile
        import textwrap
        
        # Create a temporary file with the launcher script content
        fd, temp_script_path = tempfile.mkstemp(suffix='.py', prefix='vllm_launcher_')
        
        launcher_code = textwrap.dedent('''
            #!/usr/bin/env python3
            """
            Temporary vLLM server launcher script
            """
            
            import sys
            import subprocess
            import os
            import time
            import argparse
            import signal
            
            def start_vllm_server(model_name, port=8000, tensor_parallel_size=1, max_model_len=None, gpu_memory_util=0.9):
                """Start vLLM server with specified parameters"""
                
                # Kill any existing server on the port
                try:
                    subprocess.run(["pkill", "-f", "vllm.entrypoints.openai.api_server"], 
                                  timeout=10, capture_output=True)
                    time.sleep(2)
                except:
                    pass
                
                # Build command
                cmd = [
                    sys.executable, "-m", "vllm.entrypoints.openai.api_server",
                    "--model", model_name,
                    "--host", "0.0.0.0",
                    "--port", str(port),
                    "--tensor-parallel-size", str(tensor_parallel_size),
                    "--gpu-memory-utilization", str(gpu_memory_util)
                ]
                
                if max_model_len:
                    cmd.extend(["--max-model-len", str(max_model_len)])
                
                print(f"Starting vLLM server: {' '.join(cmd)}")
                
                # Create clean environment without debugger variables
                clean_env = {}
                for key, value in os.environ.items():
                    if not any(debug_key in key.upper() for debug_key in ['DEBUGPY', 'PYDEVD']):
                        clean_env[key] = value
                
                # Remove debugger paths from PYTHONPATH if present
                if 'PYTHONPATH' in clean_env:
                    pythonpath_parts = clean_env['PYTHONPATH'].split(':')
                    clean_pythonpath = [p for p in pythonpath_parts if 'debugpy' not in p and 'pydevd' not in p]
                    if clean_pythonpath:
                        clean_env['PYTHONPATH'] = ':'.join(clean_pythonpath)
                    else:
                        del clean_env['PYTHONPATH']
                
                # Start server as daemon if requested
                if '--daemon' in sys.argv:
                    # Start server in background
                    process = subprocess.Popen(cmd, env=clean_env, start_new_session=True,
                                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    print(f"Started vLLM server as daemon with PID: {process.pid}")
                else:
                    # Start server in foreground
                    subprocess.run(cmd, env=clean_env)
            
            if __name__ == "__main__":
                parser = argparse.ArgumentParser(description="Start vLLM server")
                parser.add_argument("--model", required=True, help="Model name")
                parser.add_argument("--port", type=int, default=8000, help="Port number")
                parser.add_argument("--tensor-parallel-size", type=int, default=1, help="Tensor parallel size")
                parser.add_argument("--max-model-len", type=int, help="Maximum model length")
                parser.add_argument("--gpu-memory-util", type=float, default=0.9, help="GPU memory utilization")
                parser.add_argument("--daemon", action="store_true", help="Run as daemon")
                
                args = parser.parse_args()
                
                start_vllm_server(
                    model_name=args.model,
                    port=args.port,
                    tensor_parallel_size=args.tensor_parallel_size,
                    max_model_len=args.max_model_len,
                    gpu_memory_util=args.gpu_memory_util
                )
        ''')
        
        try:
            with os.fdopen(fd, 'w') as f:
                f.write(launcher_code)
            
            # Make the script executable
            os.chmod(temp_script_path, 0o755)
            
            logger.info(f"Created temporary vLLM launcher script: {temp_script_path}")
            return temp_script_path
            
        except Exception as e:
            os.close(fd)  # Clean up if writing failed
            os.unlink(temp_script_path)
            raise Exception(f"Failed to create temporary launcher script: {e}")

    def _start_server_standalone(self, tensor_parallel_size):
        """Start server using standalone script"""
        import subprocess
        import torch
        import os
        
        # Find the standalone launcher script - support both development and PyPI installs
        script_path = self._find_vllm_launcher_script()
        
        # Build command for standalone launcher
        cmd = [
            "python", script_path,
            "--model", self.model_name,
            "--port", "8000",
            "--tensor-parallel-size", str(tensor_parallel_size)
        ]
        
        # Add daemon flag unless explicitly disabled via environment variable or debug mode
        # Check if we're in debug mode by examining the current logging level
        import logging
        current_logger = logging.getLogger()
        is_debug_mode = current_logger.getEffectiveLevel() <= logging.DEBUG
        
        if not (os.getenv('VLLM_NO_DAEMON', '').lower() in ('1', 'true', 'yes') or is_debug_mode):
            cmd.append("--daemon")
        
        # Add memory optimization for smaller GPUs
        if torch.cuda.is_available():
            gpu_memory = torch.cuda.get_device_properties(0).total_memory / (1024**3)  # GB
            if gpu_memory < 40:  # Less than 40GB VRAM
                cmd.extend([
                    "--gpu-memory-util", "0.8",
                    "--max-model-len", "4096"
                ])
        
        logger.info(f"Starting vLLM server via standalone launcher: {' '.join(cmd)}")
        
        # Check if daemon mode is disabled
        daemon_mode = "--daemon" in cmd
        
        if daemon_mode:
            # Daemon mode: start launcher and wait for it to complete
            launcher_timeout = 120  # 2 minutes for launcher to complete
            
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=launcher_timeout)
                
                if result.returncode == 0:
                    logger.info("vLLM server launcher completed successfully")
                    logger.debug(f"Launcher stdout: {result.stdout}")
                    # The actual server process is running as daemon, we don't have direct handle
                    self.server_process = None  # We don't manage the daemon directly
                    return True
                else:
                    logger.error(f"vLLM server launcher failed with return code {result.returncode}")
                    logger.error(f"Launcher stderr: {result.stderr}")
                    logger.error(f"Launcher stdout: {result.stdout}")
                    return False
                    
            except subprocess.TimeoutExpired:
                logger.error(f"vLLM server launcher timed out after {launcher_timeout} seconds")
                logger.error("This may happen if the model is large and takes time to download/load")
                return False
                
        else:
            # Non-daemon mode: start launcher and let it stream output
            logger.info("Starting vLLM server in non-daemon mode (output will be visible)")
            try:
                # Start the launcher without capturing output so logs are visible
                process = subprocess.Popen(cmd, stdout=None, stderr=None)
                self.server_process = process
                
                # Give the server a moment to start
                import time
                time.sleep(5)
                
                # Check if the process is still running (hasn't crashed immediately)
                if process.poll() is None:
                    logger.info("vLLM server launcher started successfully in foreground mode")
                    return True
                else:
                    logger.error(f"vLLM server launcher exited immediately with code {process.returncode}")
                    return False
                    
            except Exception as e:
                logger.error(f"Failed to start vLLM server launcher: {e}")
                return False
    
    def _wait_for_server(self, timeout=300):
        """Wait for vLLM server to be ready"""
        import time
        import requests
        
        start_time = time.time()
        
        logger.info(f"Waiting for vLLM server to start (timeout: {timeout}s)...")
        
        while (time.time() - start_time) < timeout:
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
        logger.error("Server startup failed")
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

    def extract_references(self, bibliography_text: str) -> List[str]:
        return self.extract_references_with_chunking(bibliography_text)
    
    def _create_extraction_prompt(self, bibliography_text: str) -> str:
        """Create prompt for reference extraction"""
        return LLMProviderMixin._create_extraction_prompt(self, bibliography_text)
    
    def _call_llm(self, prompt: str) -> str:
        """Make the actual vLLM API call and return the response text"""
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
            
            return content or ""
            
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
        logger.info("Shutting down vLLM server...")
        try:
            self._kill_existing_server()
        except Exception as e:
            logger.error(f"Error during vLLM server cleanup: {e}")
    
    def __del__(self):
        """Cleanup on deletion"""
        self.cleanup()
