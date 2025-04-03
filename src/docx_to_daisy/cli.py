import argparse
import os
from docx import Document
from lxml import etree
import pyttsx3

def parse_docx(file_path):
    doc = Document(file_path)
    content = []
    for para in doc.paragraphs:
        style = para.style.name
        text = para.text.strip()
        if text:
            content.append({'style': style, 'text': text})
    return content


def convert_to_daisy_xml(parsed_content):
    nsmap = {'dtb': 'http://www.daisy.org/z3986/2005/dtbook/'}
    root = etree.Element(
        '{http://www.daisy.org/z3986/2005/dtbook/}dtbook', nsmap=nsmap, version='2005-3')
    body = etree.SubElement(
        root, '{http://www.daisy.org/z3986/2005/dtbook/}body')

    for item in parsed_content:
        tag_prefix = '{http://www.daisy.org/z3986/2005/dtbook/}'
        if 'Heading' in item['style']:
            try:
                level = int(item['style'].split()[-1])
                level = min(level, 6)
                h_tag = etree.SubElement(body, f'{tag_prefix}h{level}')
                h_tag.text = item['text']
            except:
                p = etree.SubElement(body, f'{tag_prefix}p')
                p.text = item['text']
        else:
            p = etree.SubElement(body, f'{tag_prefix}p')
            p.text = item['text']

    return etree.tostring(root, pretty_print=True, xml_declaration=True, encoding='UTF-8')

def text_to_audio(text, filename):
    engine = pyttsx3.init()
    engine.save_to_file(text, filename)
    engine.runAndWait()

def save_output(xml_data, output_dir):
    os.makedirs(output_dir, exist_ok=True)
    xml_path = os.path.join(output_dir, 'dtbook.xml')
    with open(xml_path, 'wb') as f:
        f.write(xml_data)
    print(f"DAISY XML saved to: {xml_path}")

def generate_audio(parsed_content, output_dir):
    audio_dir = os.path.join(output_dir, 'audio')
    os.makedirs(audio_dir, exist_ok=True)
    for i, item in enumerate(parsed_content):
        filename = os.path.join(audio_dir, f'{i:03}.mp3')
        text_to_audio(item['text'], filename)
    print(f"Audio files saved to: {audio_dir}")

def main():
    parser = argparse.ArgumentParser(description="Convert DOCX to DAISY format (XML + optional TTS audio)")
    parser.add_argument('input', help="Path to the DOCX file")
    parser.add_argument('-o', '--output', default='output_daisy', help="Output directory")
    parser.add_argument('--audio', action='store_true', help="Generate audio files using TTS")

    args = parser.parse_args()

    parsed_content = parse_docx(args.input)
    xml_data = convert_to_daisy_xml(parsed_content)
    save_output(xml_data, args.output)

    if args.audio:
        generate_audio(parsed_content, args.output)