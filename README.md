# DOCX to DAISY CLI Tool

This is a CLI tool to convert `.docx` files to DAISY format (XML + optional TTS audio).

## Usage

```bash
# Setup with uv
uv venv
source .venv/bin/activate
uv pip install -e .

# Run the tool
docx-to-daisy input.docx -o output_dir --audio
```