#!/usr/bin/env python3

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


class Colors:
    """ANSI color codes for terminal output"""
    RED = '\033[0;31m'
    GREEN = '\033[0;32m'
    YELLOW = '\033[1;33m'
    BLUE = '\033[0;34m'
    NC = '\033[0m'  # No Color


class Logger:
    """Simple logging utility with colorized output"""
    
    @staticmethod
    def info(message):
        print(f"{Colors.GREEN}[INFO]{Colors.NC} {message}")
    
    @staticmethod
    def ok(message):
        print(f"{Colors.BLUE}[OK]{Colors.NC} {message}")
    
    @staticmethod
    def warn(message):
        print(f"{Colors.YELLOW}[WARN]{Colors.NC} {message}")
    
    @staticmethod
    def error(message):
        print(f"{Colors.RED}[ERROR]{Colors.NC} {message}", file=sys.stderr)


class AmadeusNodeBuilder:
    """Production-ready Amadeus blockchain node builder and runner"""
    
    def __init__(self, repo_dir="amadeus-node", port=8080, workdir="/tmp/amadeus", 
                 container_runtime="auto"):
        self.repo_url = "https://github.com/amadeusprotocol/node.git"
        self.repo_dir = Path(repo_dir)
        self.builder_image = "erlang_builder"
        self.binary_name = "amadeusd"
        self.port = port
        self.workdir = workdir
        self.container_runtime = container_runtime
        self.runtime_cmd = None
        
    def check_command_exists(self, command):
        """Check if a command exists in PATH"""
        return shutil.which(command) is not None
    
    def detect_container_runtime(self):
        """Detect available container runtime (Docker preferred, Podman fallback)"""
        if self.container_runtime == "auto":
            if self.check_command_exists("docker"):
                self.runtime_cmd = "docker"
                Logger.info("Using Docker as container runtime")
            elif self.check_command_exists("podman"):
                self.runtime_cmd = "podman"
                Logger.info("Using Podman as container runtime")
            else:
                Logger.error("No container runtime found. Please install Docker or Podman.")
                sys.exit(1)
        elif self.container_runtime == "docker":
            if not self.check_command_exists("docker"):
                Logger.error("Docker not found but explicitly requested")
                sys.exit(1)
            self.runtime_cmd = "docker"
            Logger.info("Using Docker as container runtime")
        elif self.container_runtime == "podman":
            if not self.check_command_exists("podman"):
                Logger.error("Podman not found but explicitly requested")
                sys.exit(1)
            self.runtime_cmd = "podman"
            Logger.info("Using Podman as container runtime")
        else:
            Logger.error(f"Invalid container runtime: {self.container_runtime}")
            sys.exit(1)
    
    def run_command(self, cmd, cwd=None, check=True, capture_output=False):
        """Run a command with proper error handling"""
        Logger.info(f"Running: {' '.join(cmd)}")
        
        try:
            result = subprocess.run(
                cmd,
                cwd=cwd,
                check=check,
                capture_output=capture_output,
                text=True
            )
            if capture_output:
                return result.stdout.strip()
            return result
        except subprocess.CalledProcessError as e:
            Logger.error(f"Command failed: {' '.join(cmd)}")
            Logger.error(f"Exit code: {e.returncode}")
            if e.stdout:
                Logger.error(f"STDOUT: {e.stdout}")
            if e.stderr:
                Logger.error(f"STDERR: {e.stderr}")
            sys.exit(e.returncode)
    
    def check_dependencies(self):
        """Check and verify all required dependencies"""
        Logger.info("Checking dependencies...")
        
        dependencies = ["git", "make"]
        missing_deps = []
        
        for dep in dependencies:
            if not self.check_command_exists(dep):
                missing_deps.append(dep)
        
        if missing_deps:
            Logger.error(f"Missing dependencies: {', '.join(missing_deps)}")
            Logger.error("Please install missing dependencies and try again")
            sys.exit(1)
        
        self.detect_container_runtime()
        Logger.ok("All dependencies satisfied")
    
    def clone_repository(self):
        """Clone or update the Amadeus node repository"""
        Logger.info("Cloning/updating repository...")
        
        if self.repo_dir.exists():
            Logger.info("Repository directory exists, updating...")
            self.run_command(["git", "pull", "origin", "main"], cwd=self.repo_dir, check=False)
        else:
            Logger.info(f"Cloning repository to {self.repo_dir}")
            self.run_command(["git", "clone", self.repo_url, str(self.repo_dir)])
        
        # Resolve repo_dir and check for build.Dockerfile
        repo_dir = Path(self.repo_dir).resolve()
        
        if not (repo_dir / "build.Dockerfile").exists():
            candidate = repo_dir / "ex"
            if (candidate / "build.Dockerfile").exists():
                repo_dir = candidate
                self.repo_dir = repo_dir
                Logger.info(f"Using build.Dockerfile from ex/ subdirectory: {repo_dir}")
            else:
                Logger.error("build.Dockerfile not found in repo root or ex/ subdirectory")
                sys.exit(1)
        
        Logger.ok("Repository ready")
    
    def build_builder_image(self):
        """Build the Erlang builder Docker image"""
        Logger.info("Building Erlang builder image...")
        
        dockerfile_path = self.repo_dir / "build.Dockerfile"
        if not dockerfile_path.exists():
            Logger.error(f"build.Dockerfile not found at {dockerfile_path}")
            sys.exit(1)
        
        cmd = [
            self.runtime_cmd, "build",
            "--tag", self.builder_image,
            "-f", "build.Dockerfile",
            "."
        ]
        
        self.run_command(cmd, cwd=self.repo_dir)
        Logger.ok("Erlang builder image built successfully")
    
    def compile_node(self):
        """Compile the Amadeus node using the containerized build"""
        Logger.info("Compiling Amadeus node...")
        
        cmd = [
            self.runtime_cmd, "run", "--rm",
            "-v", f"{self.repo_dir.absolute()}:/app",
            "-w", "/app",
            self.builder_image,
            "make"
        ]
        
        self.run_command(cmd)
        Logger.ok("Node compilation completed successfully")
    
    def verify_binary(self):
        """Verify that the amadeusd binary exists and is executable"""
        Logger.info("Verifying amadeusd binary...")
        
        binary_path = self.repo_dir / self.binary_name
        
        if not binary_path.exists():
            Logger.error(f"Binary not found at {binary_path}")
            
            # Search for binary in repository
            result = self.run_command(
                ["find", str(self.repo_dir), "-name", self.binary_name, "-type", "f"],
                capture_output=True
            )
            
            if result:
                Logger.warn(f"Found binary at: {result}")
                binary_path = Path(result)
            else:
                Logger.error("Could not find amadeusd binary anywhere in repository")
                sys.exit(1)
        
        # Make binary executable
        os.chmod(binary_path, 0o755)
        Logger.ok(f"Binary verified and made executable: {binary_path}")
        
        return binary_path
    
    def create_work_directory(self):
        """Create the work directory for the node"""
        Logger.info(f"Creating work directory: {self.workdir}")
        
        workdir_path = Path(self.workdir)
        workdir_path.mkdir(parents=True, exist_ok=True)
        
        Logger.ok("Work directory created")
    
    def run_node(self, binary_path):
        """Run the Amadeus node in TESTNET mode"""
        Logger.info("Starting Amadeus node in TESTNET mode...")
        Logger.info(f"Configuration:")
        Logger.info(f"  TESTNET=true")
        Logger.info(f"  WORKFOLDER={self.workdir}")
        Logger.info(f"  HTTP_IPV4=127.0.0.1")
        Logger.info(f"  HTTP_PORT={self.port}")
        
        # Set environment variables
        env = os.environ.copy()
        env.update({
            "TESTNET": "true",
            "WORKFOLDER": self.workdir,
            "HTTP_IPV4": "127.0.0.1",
            "HTTP_PORT": str(self.port)
        })
        
        Logger.info(f"Starting node... (Press Ctrl+C to stop)")
        Logger.info(f"Node will be accessible at http://127.0.0.1:{self.port}")
        
        # Run the node
        try:
            os.execve(str(binary_path), [str(binary_path)], env)
        except OSError as e:
            Logger.error(f"Failed to execute node: {e}")
            sys.exit(1)
    
    def build_and_run(self):
        """Main execution flow: build and run the node"""
        Logger.info("Starting Amadeus node deployment...")
        
        # Check dependencies
        self.check_dependencies()
        
        # Clone repository
        self.clone_repository()
        
        # Build builder image
        self.build_builder_image()
        
        # Compile node
        self.compile_node()
        
        # Verify binary
        binary_path = self.verify_binary()
        
        # Create work directory
        self.create_work_directory()
        
        # Run node
        self.run_node(binary_path)


def parse_arguments():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description="Build and run Amadeus blockchain node",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                                    # Use default settings
  %(prog)s --port 9090                       # Use custom port
  %(prog)s --container-runtime podman        # Force Podman usage
  %(prog)s --repo-dir /opt/amadeus           # Custom repository directory
        """
    )
    
    parser.add_argument(
        "--repo-dir",
        default="amadeus-node",
        help="Repository directory (default: amadeus-node)"
    )
    
    parser.add_argument(
        "--port",
        type=int,
        default=8080,
        help="HTTP port for the node (default: 8080)"
    )
    
    parser.add_argument(
        "--workdir",
        default="/tmp/amadeus",
        help="Work directory for node data (default: /tmp/amadeus)"
    )
    
    parser.add_argument(
        "--container-runtime",
        choices=["auto", "docker", "podman"],
        default="auto",
        help="Container runtime to use (default: auto)"
    )
    
    return parser.parse_args()


def main():
    """Main entry point"""
    args = parse_arguments()
    
    try:
        builder = AmadeusNodeBuilder(
            repo_dir=args.repo_dir,
            port=args.port,
            workdir=args.workdir,
            container_runtime=args.container_runtime
        )
        
        builder.build_and_run()
        
    except KeyboardInterrupt:
        Logger.info("Received interrupt signal, shutting down...")
        sys.exit(0)
    except Exception as e:
        Logger.error(f"Unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
