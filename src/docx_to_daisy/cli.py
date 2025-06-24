import zipfile
import os
import uuid
import argparse
import re
import logging
from docx import Document  # python-docx 라이브러리
from lxml import etree  # lxml 라이브러리
from datetime import datetime
from .markers import MarkerProcessor  # 마커 처리기 임포트

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def split_text_to_words(text):
    """텍스트를 단어로 분리하는 함수
    
    Args:
        text (str): 분리할 텍스트
        
    Returns:
        list: 분리된 단어들의 리스트
    """
    # <br/> 태그 제거
    text = text.replace('<br/>', ' ')
    
    # 문장 부호 패턴 정의
    punctuation_pattern = r'[.。,，!！?？:：;；]'

    # 1. 먼저 공백으로 단어들을 분리
    words = text.strip().split()

    result = []
    for word in words:
        # 2. 각 단어에서 문장 부호가 있는지 확인
        if re.search(punctuation_pattern, word):
            # 문장 부호가 단어 중간에 있는 경우는 그대로 유지
            if not re.match(f'^{punctuation_pattern}', word) and not re.search(f'{punctuation_pattern}$', word):
                result.append(word)
                continue

            # 문장 부호로 시작하는 경우
            if re.match(f'^{punctuation_pattern}', word):
                punct = re.match(f'^({punctuation_pattern}+)', word).group(1)
                remaining = word[len(punct):]
                if punct:
                    result.append(punct)
                if remaining:
                    result.append(remaining)
                continue

            # 문장 부호로 끝나는 경우
            if re.search(f'{punctuation_pattern}$', word):
                match = re.search(f'({punctuation_pattern}+)$', word)
                punct = match.group(1)
                text_part = word[:-len(punct)]
                if text_part:
                    result.append(text_part + punct)  # 문장 부호를 단어에 붙임
                else:
                    result.append(punct)
                continue

        # 문장 부호가 없는 일반 단어
        result.append(word)

    return result


def find_all_images(document):
    """문서에서 모든 이미지와 그 위치를 찾습니다."""
    images = []
    # Word 문서의 네임스페이스 정의
    nsmap = {
        'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main',
        'wp': 'http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing',
        'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
        'pic': 'http://schemas.openxmlformats.org/drawingml/2006/picture',
        'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
    }
    
    for para_idx, para in enumerate(document.paragraphs):
        # 현재 단락의 전체 텍스트
        current_para_text = para.text
        
        # 이전 단락의 텍스트 (있는 경우)
        prev_para_text = document.paragraphs[para_idx-1].text if para_idx > 0 else ""
        
        # 다음 단락의 텍스트 (있는 경우)
        next_para_text = document.paragraphs[para_idx+1].text if para_idx < len(document.paragraphs)-1 else ""
        
        for run_idx, run in enumerate(para.runs):
            # 이미지 요소 찾기 (네임스페이스 명시)
            drawing = run._element.find('.//w:drawing', namespaces=nsmap)
            pict = run._element.find('.//w:pict', namespaces=nsmap)
            
            if drawing is not None or pict is not None:
                # 이미지 관계 ID 찾기
                blip = None
                if drawing is not None:
                    blip = drawing.find('.//a:blip', namespaces=nsmap)
                elif pict is not None:
                    blip = pict.find('.//a:blip', namespaces=nsmap)
                
                if blip is not None:
                    # 이미지 관계 ID 추출
                    embed = blip.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed')
                    if embed:
                        # 이미지 데이터 가져오기
                        image_part = document.part.related_parts[embed]
                        image_data = image_part.blob
                        
                        # 이미지가 발견되면 앞뒤 텍스트 출력
                        print(f"\n이미지 발견 (위치: 단락 {para_idx}, 런 {run_idx})")
                        print(f"이전 단락: {prev_para_text}")
                        print(f"현재 단락: {current_para_text}")
                        print(f"다음 단락: {next_para_text}")
                        print(f"이미지 크기: {len(image_data)} bytes")
                        
                        images.append({
                            'paragraph_index': para_idx,
                            'run_index': run_idx,
                            'paragraph': para,
                            'run': run,
                            'image_data': image_data,
                            'image_rid': embed
                        })
    return images


def analyze_image_context(document, image_info, window_size=2):
    """이미지 주변의 텍스트를 분석하여 이미지 설명을 찾습니다."""
    para_idx = image_info['paragraph_index']
    para = image_info['paragraph']
    
    # 이미지가 있는 단락의 전체 텍스트
    current_para_text = para.text
    
    # 이전 단락들의 텍스트 (window_size개)
    previous_paras = []
    for i in range(max(0, para_idx - window_size), para_idx):
        previous_paras.append(document.paragraphs[i].text)
    
    # 이후 단락들의 텍스트 (window_size개)
    next_paras = []
    for i in range(para_idx + 1, min(len(document.paragraphs), para_idx + window_size + 1)):
        next_paras.append(document.paragraphs[i].text)
    
    # 이미지 설명 패턴 찾기
    # 1. 대괄호로 둘러싸인 텍스트 찾기
    bracket_pattern = r'\[(.*?)\]'
    bracket_matches = re.finditer(bracket_pattern, current_para_text)
    
    # 2. 이미지 관련 키워드 찾기
    image_keywords = ['그림', '사진', '이미지', 'QR', '코드', '차트', '표', '다이어그램']
    
    # 이미지 설명 후보들
    candidates = []
    
    # 현재 단락에서 찾기
    for match in bracket_matches:
        text = match.group(1)
        if any(keyword in text for keyword in image_keywords):
            candidates.append({
                'text': text,
                'position': 'current',
                'distance': abs(match.start() - image_info['run_index'])
            })
    
    # 이전 단락들에서 찾기
    for idx, prev_text in enumerate(previous_paras):
        for match in re.finditer(bracket_pattern, prev_text):
            text = match.group(1)
            if any(keyword in text for keyword in image_keywords):
                candidates.append({
                    'text': text,
                    'position': 'previous',
                    'distance': len(previous_paras) - idx
                })
    
    # 이후 단락들에서 찾기
    for idx, next_text in enumerate(next_paras):
        for match in re.finditer(bracket_pattern, next_text):
            text = match.group(1)
            if any(keyword in text for keyword in image_keywords):
                candidates.append({
                    'text': text,
                    'position': 'next',
                    'distance': idx + 1
                })
    
    # 가장 적절한 설명 선택
    if candidates:
        # 거리와 위치를 고려하여 가장 적절한 설명 선택
        best_candidate = min(candidates, key=lambda x: (x['distance'], 
            0 if x['position'] == 'current' else 
            1 if x['position'] == 'previous' else 2))
        return best_candidate['text']
    
    return None


def create_daisy_book(docx_file_path, output_dir, book_title=None, book_author=None, book_publisher=None, book_language="ko"):
    """DOCX 파일을 DAISY 형식으로 변환합니다.

    Args:
        docx_file_path (str): 변환할 DOCX 파일 경로
        output_dir (str): 생성된 DAISY 파일 저장 폴더
        book_title (str, optional): 책 제목. 기본값은 None (DOCX 파일명 사용)
        book_author (str, optional): 저자. 기본값은 None
        book_publisher (str, optional): 출판사. 기본값은 None
        book_language (str, optional): 언어 코드 (ISO 639-1). 기본값은 "ko"
    """
    # 이미지 설명 처리 함수 정의
    def get_clean_description(desc_list):
        """이미지 설명 목록에서 중복을 제거하고 깔끔한 설명을 반환합니다"""
        if not desc_list:
            return None
        
        # 중복 제거
        unique_desc = []
        seen = set()
        for desc in desc_list:
            if desc not in seen:
                seen.add(desc)
                unique_desc.append(desc)
        
        # 설명이 너무 길면 첫 번째 항목만 반환
        if len(unique_desc) > 0:
            return unique_desc[0]
        return None
    
    # --- 출력 디렉토리 생성 ---
    os.makedirs(output_dir, exist_ok=True)

    # --- DOCX 파일 읽기 및 구조 분석 ---
    try:
        document = Document(docx_file_path)
    except FileNotFoundError:
        print(f"오류: DOCX 파일을 찾을 수 없습니다 - {docx_file_path}")
        return
    except Exception as e:
        print(f"오류: DOCX 파일을 읽는 중 오류가 발생했습니다 - {str(e)}")
        return

    # --- 기본 정보 설정 ---
    # book_title 확인
    if book_title is None or not isinstance(book_title, str) or len(book_title.strip()) == 0:
        raise ValueError("책 제목이 제공되지 않았거나 유효하지 않습니다. 변환을 진행할 수 없습니다.")
    
    # book_author 확인
    if book_author is None or not isinstance(book_author, str) or len(book_author.strip()) == 0:
        raise ValueError("저자 정보가 제공되지 않았거나 유효하지 않습니다. 변환을 진행할 수 없습니다.")
    

    book_title = str(book_title)
    book_author = str(book_author)
    book_publisher = str(book_publisher)


    # book_uid에 책 제목을 포함시켜 DAISY 열 때 표시될 이름 설정
    safe_title = book_title.replace(" ", "_").replace("/", "_").replace("\\", "_").replace(":", "_")
    
    book_uid = f"BOOK-{safe_title}"  # 제목을 포함한 식별자
    print("book_uid", book_uid)

    content_structure = []
    element_counter = 0
    sent_counter = 0

    # doctitle과 docauthor를 위한 ID 미리 할당
    doctitle_id = "id_1"
    docauthor_id = "id_2"
    sent_counter = 2  # doctitle과 docauthor 이후부터 시작
    element_counter = 2  # doctitle과 docauthor 이후부터 시작

    # 이미지 관련 정보 저장 변수
    image_info = {}  # 이미지 번호 -> {제목, 설명, 위치} 매핑
    
    # 0. 문서 body child 순서를 맵으로 생성하여 실제 위치 사용
    body_children = list(document._element.body.iterchildren())
    element_index = {id(child): idx for idx, child in enumerate(body_children)}

    # 1. 문서에서 모든 이미지 찾기
    print("문서에서 이미지 찾는 중...")
    images = find_all_images(document)
    print(f"총 {len(images)}개의 이미지 발견")
    
    # 2. 문서에서 모든 이미지 추출
    print(f"문서에서 이미지 추출 중...")
    image_counter = 0
    image_relations = []
    
    # 모든 이미지 관계 수집
    for rel_id, rel in document.part.rels.items():
        if "image" in rel.reltype:
            try:
                # 이미지 관계 정보 저장
                image_relations.append(rel)
                print(f"이미지 관계 발견: {rel_id}, {rel.reltype}")
            except Exception as e:
                print(f"이미지 관계 처리 오류: {str(e)}")
    
    print(f"문서에서 {len(image_relations)}개의 이미지 관계 발견")
    
    # 이미지 매핑 정보 초기화
    image_mapping = {}  # 이미지 번호 -> 이미지 관계 매핑

    # 이미지 처리
    for i, img in enumerate(images, 1):
        img_num = str(i)
        try:
            image_counter += 1
            element_counter += 1
            sent_counter += 1
            
            # 이미지 ID 생성
            elem_id = f"id_{element_counter}"
            sent_id = f"id_{sent_counter}"
            
            # 이미지 파일 저장
            image_ext = os.path.splitext(rel.target_ref)[1]
            if not image_ext:  # 확장자가 없으면 기본값 사용
                image_ext = ".jpeg"
            
            image_filename = f"image{img_num}{image_ext}"
            image_path = os.path.join(output_dir, image_filename)
            
            # 이미지 데이터 저장
            with open(image_path, "wb") as img_file:
                img_file.write(img['image_data'])
            print(f"이미지 {img_num} 저장: {image_path}")
            
            # 이미지 정보를 content_structure에 추가
            para_position = element_index.get(id(img['paragraph']._element), img['paragraph_index'])
            content_structure.append({
                "type": "image",
                "src": image_filename,
                "alt_text": f"이미지 {img_num}",
                "id": elem_id,
                "sent_id": sent_id,
                "level": 0,
                "markers": [],
                "smil_file": "dtbook.smil",
                "position": para_position,
                "insert_before": False
            })
            print(f"이미지 {img_num}를 content_structure에 추가함 (위치: {para_position})")
        except Exception as e:
            print(f"이미지 {img_num} 처리 중 오류 발생: {str(e)}")
    
    print(f"{image_counter}개 이미지 추출 완료.")

    # DOCX의 단락(paragraph)을 순회하며 구조 파악
    print("DOCX 파일 분석 중...")
    
    # 표 위치 추적을 위한 변수
    table_positions = {}  # 표 인덱스 -> 단락 인덱스 매핑
    
    # 단락 처리
    for para_idx, para in enumerate(document.paragraphs):
        text_raw = para.text  # 원본 텍스트(앞뒤 공백 유지)
        style_name = para.style.name.lower()  # 스타일 이름을 소문자로 비교

        # 표 제목 패턴 체크 제거 - 모든 단락을 처리

        # <br/> 태그(또는 변형) 기준으로 세그먼트를 분리합니다.
        br_segments = re.split(r'<br\s*/?>', text_raw, flags=re.IGNORECASE)

        # 세그먼트별 처리
        for seg_idx, seg_text in enumerate(br_segments):
            # <br/> 태그가 있었던 자리에 빈 문단을 생성합니다.
            if seg_idx > 0:
                element_counter += 1
                sent_counter += 1
                blank_elem_id = f"id_{element_counter}"
                blank_sent_id = f"id_{sent_counter}"
                content_structure.append({
                    "type": "p",
                    "text": "<br/>",  # br 태그가 포함된 문단
                    "words": ["<br/>"],
                    "id": blank_elem_id,
                    "sent_id": blank_sent_id,
                    "level": 0,
                    "markers": [],
                    "smil_file": "dtbook.smil",
                    "position": para_idx,
                    "insert_before": False
                })

            # 세그먼트 자체가 비어 있으면(공백만) 넘어갑니다.
            if not seg_text.strip():
                continue

            # 마커 처리
            processed_text, markers = MarkerProcessor.process_text(seg_text.strip())

            # 페이지 마커가 있는 경우 먼저 처리
            for marker in markers:
                if marker.type == "page":
                    element_counter += 1
                    sent_counter += 1
                    elem_id = f"id_{element_counter}"
                    sent_id = f"id_{sent_counter}"
                    content_structure.append({
                        "type": "pagenum",
                        "text": marker.value,
                        "words": [marker.value],
                        "id": elem_id,
                        "sent_id": sent_id,
                        "level": 0,
                        "markers": [marker],
                        "smil_file": "dtbook.smil",
                        "position": para_idx,
                        "insert_before": True  # 단락 앞에 페이지 번호 삽입
                    })

                    # 마커만 있고 실제 내용이 없는 경우 건너뜀
                    if not processed_text.strip():
                        continue

            element_counter += 1
            sent_counter += 1
            elem_id = f"id_{element_counter}"
            sent_id = f"id_{sent_counter}"

            # 단어 분리
            words = split_text_to_words(processed_text)

            # 스타일 이름에 따른 구조 매핑
            content_structure.append({
                "type": "h1" if style_name.startswith('heading 1') or style_name == '제목 1' else
                "h2" if style_name.startswith('heading 2') or style_name == '제목 2' else
                "h3" if style_name.startswith('heading 3') or style_name == '제목 3' else
                "h4" if style_name.startswith('heading 4') or style_name == '제목 4' else
                "h5" if style_name.startswith('heading 5') or style_name == '제목 5' else
                "h6" if style_name.startswith('heading 6') or style_name == '제목 6' else
                "p",
                "text": processed_text,
                "words": words,
                "id": elem_id,
                "sent_id": sent_id,
                "level": 1 if style_name.startswith('heading 1') or style_name == '제목 1' else
                        2 if style_name.startswith('heading 2') or style_name == '제목 2' else
                        3 if style_name.startswith('heading 3') or style_name == '제목 3' else
                        4 if style_name.startswith('heading 4') or style_name == '제목 4' else
                        5 if style_name.startswith('heading 5') or style_name == '제목 5' else
                        6 if style_name.startswith('heading 6') or style_name == '제목 6' else
                        0,
                "markers": markers,
                "smil_file": "dtbook.smil",
                "position": para_idx,
                "insert_before": False  # 일반 텍스트는 순서대로 삽입
            })

    # 표 처리 추가
    print("표 처리 중...")
    
    # 문서의 실제 표만 처리
    if len(document.tables) > 0:
        print(f"문서에 {len(document.tables)}개의 표 발견")
        
        # 각 표 처리
        for table_idx, table in enumerate(document.tables, 1):
            element_counter += 1
            sent_counter += 1
            elem_id = f"id_{element_counter}"
            sent_id = f"id_{sent_counter}"
            
            # 표 데이터 추출
            table_data = {
                "rows": [],
                "cols": [],
                "cells": []
            }
            
            # 행과 열 정보 추출
            for row_idx, row in enumerate(table.rows):
                row_data = []
                for col_idx, cell in enumerate(row.cells):
                    # 셀 텍스트 추출
                    cell_text = " ".join(para.text for para in cell.paragraphs)
                    row_data.append(cell_text)
                    
                    # 셀 병합 정보 확인
                    rowspan = 1
                    colspan = 1
                    is_merged_cell = False
                    
                    if hasattr(cell, '_tc') and hasattr(cell._tc, 'vMerge'):
                        if cell._tc.vMerge == 'restart':
                            is_merged_cell = True
                            # 세로 병합 계산: 연속된 'continue' 셀 개수 세기
                            for next_row_idx in range(row_idx + 1, len(table.rows)):
                                if col_idx < len(table.rows[next_row_idx].cells):
                                    next_cell = table.rows[next_row_idx].cells[col_idx]
                                    if (hasattr(next_cell, '_tc') and hasattr(next_cell._tc, 'vMerge') and 
                                        next_cell._tc.vMerge == 'continue'):
                                        rowspan += 1
                                    else:
                                        break
                                else:
                                    break
                            print(f"    세로 병합 셀: ({row_idx}, {col_idx}) - rowspan={rowspan}")
                        elif cell._tc.vMerge == 'continue':
                            # 'continue' 셀은 건너뛰기 (이미 위에서 처리됨)
                            continue
                    
                    # 가로 병합 확인
                    if hasattr(cell, '_tc') and hasattr(cell._tc, 'hMerge'):
                        if cell._tc.hMerge == 'restart':
                            is_merged_cell = True
                            # 가로 병합 계산: 연속된 'continue' 셀 개수 세기
                            colspan = 1
                            for next_col_idx in range(col_idx + 1, len(row.cells)):
                                next_cell = row.cells[next_col_idx]
                                if (hasattr(next_cell, '_tc') and hasattr(next_cell._tc, 'hMerge') and 
                                    next_cell._tc.hMerge == 'continue'):
                                    colspan += 1
                                else:
                                    break
                            print(f"    가로 병합 셀: ({row_idx}, {col_idx}) - colspan={colspan}")
                        elif cell._tc.hMerge == 'continue':
                            # 'continue' 셀은 건너뛰기 (이미 위에서 처리됨)
                            continue
                    
                    # 셀 정보 저장
                    table_data["cells"].append({
                        "row": row_idx,
                        "col": col_idx,
                        "text": cell_text,
                        "is_merged": is_merged_cell,
                        "rowspan": rowspan,
                        "colspan": colspan
                    })
                
                table_data["rows"].append(row_data)
            
            # 열 정보 추출
            for col_idx in range(len(table.columns)):
                col_data = []
                for row in table.rows:
                    if col_idx < len(row.cells):
                        cell_text = " ".join(para.text for para in row.cells[col_idx].paragraphs)
                        col_data.append(cell_text)
                table_data["cols"].append(col_data)
            
            # 표의 실제 위치를 찾기 위해 문서의 모든 요소를 순회
            table_position_body = len(document.paragraphs)  # 기본값
            try:
                # 문서 body의 모든 자식 요소를 순회하면서 표의 위치 찾기
                body_element = document._element.body
                all_elements = list(body_element.iterchildren())
                
                for idx, element in enumerate(all_elements):
                    if element is table._element:
                        table_position_body = idx
                        break
                        
                print(f"표 {table_idx} 실제 위치: {table_position_body} (총 {len(all_elements)}개 요소 중)")
                
            except Exception as e:
                print(f"표 위치 계산 중 오류: {e}")
                table_position_body = len(document.paragraphs)
            
            table_title = f"표 {table_idx}"
            
            # 표 정보를 content_structure에 추가
            content_structure.append({
                "type": "table",
                "table_data": table_data,
                "id": elem_id,
                "sent_id": sent_id,
                "level": 0,
                "markers": [],
                "smil_file": "dtbook.smil",
                "position": table_position_body,  # 문서 내 실제 위치
                "insert_before": False,
                "title": table_title,
                "table_number": table_idx,  # 표 번호 저장
                "text": table_title  # text 키 추가
            })
            
            print(f"표 {table_idx} 처리 완료: {len(table_data['rows'])}행 x {len(table_data['cols'])}열, 위치: {table_position_body}")
    else:
        print("문서에 표가 없습니다.")

    # 콘텐츠를 위치에 따라 정렬
    content_structure.sort(key=lambda x: (x["position"], 
                                         x.get("image_number", float('inf')) if x["type"] == "image" else 0, 
                                         not x["insert_before"]))

    print(f"총 {len(content_structure)}개의 구조 요소 분석 완료.")

    # --- 1. DTBook XML 생성 (dtbook.xml) ---
    print("DTBook 생성 중...")
    dtbook_ns = "http://www.daisy.org/z3986/2005/dtbook/"
    dc_ns = "http://purl.org/dc/elements/1.1/"

    # 페이지 카운터 초기화
    total_pages = 0
    max_page_number = 0
    for item in content_structure:
        for marker in item.get("markers", []):
            if marker.type == "page":
                total_pages += 1
                try:
                    page_num = int(marker.value)
                    max_page_number = max(max_page_number, page_num)
                except ValueError:
                    pass

    dtbook_root = etree.Element(
        "{%s}dtbook" % dtbook_ns,
        attrib={
            "version": "2005-3"
        },
        nsmap={
            None: dtbook_ns,
            "dc": dc_ns
        }
    )

    # head 요소 추가
    head = etree.SubElement(dtbook_root, "head")

    # 필수 메타데이터 추가
    meta_uid = etree.SubElement(head, "meta",
                                name="dtb:uid",
                                content=book_uid)
    meta_title = etree.SubElement(head, "meta",
                                  name="dc:Title",
                                  content=book_title)
    meta_author = etree.SubElement(head, "meta",
                                   name="dc:Creator",
                                   content=book_author)
    meta_publisher = etree.SubElement(head, "meta",
                                   name="dc:Publisher",
                                   content=book_publisher)
    meta_language = etree.SubElement(head, "meta",
                                     name="dc:Language",
                                     content=book_language)
    meta_date = etree.SubElement(head, "meta",
                                 name="dc:Date",
                                 content=datetime.now().strftime("%Y-%m-%d"))

    # 페이지 관련 메타데이터 추가
    etree.SubElement(head, "meta",
                     name="dtb:totalPageCount",
                     content=str(total_pages))
    etree.SubElement(head, "meta",
                     name="dtb:maxPageNumber",
                     content=str(max_page_number))

    # book 요소 추가
    dtbook_book = etree.SubElement(dtbook_root, "book", showin="blp")

    # frontmatter 추가
    dtbook_frontmatter = etree.SubElement(dtbook_book, "frontmatter")

    # doctitle과 docauthor 추가
    doctitle_seq = etree.SubElement(dtbook_frontmatter, "doctitle",
                                    id="forsmil-1",
                                    smilref="dtbook.smil#sforsmil-1")
    doctitle_seq.text = book_title

    docauthor = etree.SubElement(dtbook_frontmatter, "docauthor",
                                 id="forsmil-2",
                                 smilref="dtbook.smil#sforsmil-2")
    docauthor.text = book_author

    # 출판사 추가
    docpublisher = etree.SubElement(dtbook_frontmatter, "docpublisher",
                                    id="forsmil-3",
                                    smilref="dtbook.smil#sforsmil-3")
    docpublisher.text = book_publisher

    # bodymatter 추가
    dtbook_bodymatter = etree.SubElement(dtbook_book, "bodymatter")

    # 현재 level1 요소
    current_level1 = None
    current_level = 0

    # 콘텐츠 추가
    for item in content_structure:
        if item["type"] == "pagenum":
            pagenum = etree.SubElement(
                current_level1 if current_level1 is not None else dtbook_bodymatter,
                "pagenum",
                id=f"page_{item['text']}_{item['text']}",
                smilref=f"dtbook.smil#smil_par_page_{item['text']}_{item['text']}",
                page="normal"
            )
            pagenum.text = str(item["text"])
            continue
        elif item["type"] == "image":
            if current_level1 is None:
                # level1이 없는 경우 생성
                current_level1 = etree.SubElement(dtbook_bodymatter, "level1",
                                                id=item["id"],
                                                smilref=f"dtbook.smil#smil_par_{item['id']}")
                current_level = 1
                heading = etree.SubElement(current_level1, "h1")
                heading.text = " ".join(item["words"])

            # 이미지 그룹 생성
            imggroup = etree.SubElement(
                current_level1,
                "imggroup",
                id=item["id"],
                class_="figure"
            )

            # 이미지 요소 생성
            img = etree.SubElement(
                imggroup,
                "img",
                id=f"{item['id']}_img",
                src=item["src"],
                alt=item["alt_text"]
            )
            
            # 이미지 크기를 적절히 설정
            img.set("width", "100%")
            img.set("height", "auto")
            
            # 이미지 캡션 추가
            caption = etree.SubElement(imggroup, "caption",
                                       id=f"{item['id']}_caption")
            sent = etree.SubElement(caption, "sent",
                                    id=item["sent_id"],
                                    smilref=f"dtbook.smil#smil_par_{item['sent_id']}")
            
            # 이미지 제목만 캡션으로 설정
            # w = etree.SubElement(sent, "w")
            
            # 제목 설정
            # if "title" in item and item["title"]:
            #     img_type = item.get("type", "그림")
            #     w.text = f"{img_type} {item['id'].replace('id_', '')}: {item['title']}"
            # else:
            #     w.text = item["alt_text"]
            
            # 이미지 설명이 있을 경우에만 추가
            # if "description" in item and item["description"]:
            #     desc_p = etree.SubElement(caption, "p", class_="image-description")
            #     desc_p.text = item["description"]
            
            continue
        elif item["type"] == "table":
            # 표 처리
            if current_level1 is None:
                # level1이 없는 경우 생성
                current_level1 = etree.SubElement(dtbook_bodymatter, "level1",
                                                id=item["id"],
                                                smilref=f"dtbook.smil#smil_par_{item['id']}")
                current_level = 1
                heading = etree.SubElement(current_level1, "h1")
                heading.text = "제목 없음"
            
            # 표 요소 생성
            table = etree.SubElement(current_level1, "table", 
                                    id=item["id"],
                                    class_="data-table",
                                    smilref=f"dtbook.smil#smil_par_{item['id']}",
                                    border="1")
            
            # 표 데이터 가져오기
            table_data = item["table_data"]
            
            # 표 번호 가져오기
            table_number = item.get("table_number", 1)  # 기본값 1로 설정
            
            # tbody 요소 생성
            tbody = etree.SubElement(table, "tbody")
            
            # 표 데이터로 행과 열 생성
            for row_idx, row_data in enumerate(table_data["rows"]):
                tr = etree.SubElement(tbody, "tr", 
                                     id=f"forsmil-{element_counter+row_idx}",
                                     smilref=f"dtbook.smil#smil_par_{item['id']}_cell_{row_idx}")
                
                for col_idx, cell_text in enumerate(row_data):
                    # 셀 정보 찾기
                    cell_info = next((cell for cell in table_data["cells"] 
                                    if cell["row"] == row_idx and cell["col"] == col_idx), None)
                    
                    # 병합된 셀의 경우 건너뛰기 (이미 처리됨)
                    if cell_info and cell_info["is_merged"] and (cell_info["rowspan"] > 1 or cell_info["colspan"] > 1):
                        continue
                    
                    # 셀 요소 생성
                    if col_idx == 0:
                        cell_elem = etree.SubElement(tr, "th", scope="row",
                                                    id=f"forsmil-{element_counter+row_idx*10+col_idx}",
                                                    smilref=f"dtbook.smil#smil_par_{item['id']}_cell_{row_idx}_{col_idx}")
                    else:
                        cell_elem = etree.SubElement(tr, "td",
                                                    id=f"forsmil-{element_counter+row_idx*10+col_idx}",
                                                    smilref=f"dtbook.smil#smil_par_{item['id']}_cell_{row_idx}_{col_idx}")
                    
                    # 병합 속성 설정
                    if cell_info:
                        if cell_info["rowspan"] > 1:
                            cell_elem.set("rowspan", str(cell_info["rowspan"]))
                        if cell_info["colspan"] > 1:
                            cell_elem.set("colspan", str(cell_info["colspan"]))
                    
                    # 셀 내용 추가: sent/w 태그 없이 <p> 바로 텍스트를 넣음
                    p = etree.SubElement(
                        cell_elem,
                        "p",
                        id=f"table_{item['id']}_cell_{row_idx}_{col_idx}",
                        smilref=f"dtbook.smil#smil_par_{item['id']}_cell_{row_idx}_{col_idx}"
                    )
                    # br 태그가 포함된 경우 실제 br 요소 생성
                    if item.get("text", "") == "<br/>":
                        br_elem = etree.SubElement(p, "br")
                    else:
                        p.text = cell_text.strip()
        elif item["type"].startswith("h"):
            level = int(item["type"][1])  # h1 -> 1, h2 -> 2, h3 -> 3, h4 -> 4, h5 -> 5, h6 -> 6

            if level == 1:
                # 새로운 level1 시작
                current_level1 = etree.SubElement(dtbook_bodymatter, "level1",
                                                id=item["id"],
                                                smilref=f"dtbook.smil#smil_par_{item['id']}")
                current_level = 1
                heading = etree.SubElement(current_level1, "h1")
                heading.text = " ".join(item["words"])
            else:
                # level2~6은 이전 level 내에 위치
                if current_level1 is None:
                    # level1이 없는 경우 생성
                    current_level1 = etree.SubElement(dtbook_bodymatter, "level1",
                                                    id=item["id"],
                                                    smilref=f"dtbook.smil#smil_par_{item['id']}")
                    current_level = 1
                    heading = etree.SubElement(current_level1, "h1")
                    heading.text = "제목 없음"

                # 현재 레벨에 맞는 부모 요소 찾기
                parent = current_level1
                current_level_elem = None
                for l in range(2, level):
                    level_elem = parent.find(f"level{l}")
                    if level_elem is None:
                        # 중간 레벨이 없으면 생성
                        level_elem = etree.SubElement(parent, f"level{l}",
                                                    id=item["id"],
                                                    smilref=f"dtbook.smil#smil_par_{item['id']}")
                        heading = etree.SubElement(level_elem, f"h{l}")
                        heading.text = f"제목 {l}"
                    parent = level_elem
                    current_level_elem = level_elem

                # 새로운 level 요소 생성
                new_level = etree.SubElement(parent, f"level{level}",
                                           id=item["id"],
                                           smilref=f"dtbook.smil#smil_par_{item['id']}")
                heading = etree.SubElement(new_level, f"h{level}")
                heading.text = " ".join(item["words"])

                # 현재 레벨 요소 업데이트
                if level > current_level:
                    current_level_elem = new_level
                current_level = level

            # 기타 마커 처리
            for marker in item.get("markers", []):
                if marker.type != "page":  # 페이지 마커는 이미 처리됨
                    elem_info = MarkerProcessor.create_dtbook_element(marker)
                    if elem_info:
                        marker_elem = etree.SubElement(current_level_elem or current_level1,
                                                     elem_info["tag"],
                                                     attrib=elem_info["attrs"])
                        marker_elem.text = elem_info["text"]

            # 일반 텍스트 내용 추가
            if not item["type"].startswith("h"):
                parent_elem = current_level_elem or current_level1
                p = etree.SubElement(parent_elem, "p",
                                   id=item["id"],
                                   smilref=f"dtbook.smil#smil_par_{item['id']}")
                p.text = " ".join(item["words"])
        else:
            # 일반 단락은 현재 level 요소 내에 추가
            if current_level1 is None:
                # level1이 없는 경우 생성
                current_level1 = etree.SubElement(dtbook_bodymatter, "level1",
                                                id=item["id"],
                                                smilref=f"dtbook.smil#smil_par_{item['id']}")
                # 임시 제목 추가
                temp_h1 = etree.SubElement(current_level1, "h1")
                temp_h1.text = "제목 없음"

            p = etree.SubElement(current_level1, "p",
                                 id=item["id"],
                                 smilref=f"dtbook.smil#smil_par_{item['id']}")
            p.text = " ".join(item["words"])

            # 기타 마커 처리
            for marker in item.get("markers", []):
                if marker.type != "page":  # 페이지 마커는 이미 처리됨
                    elem_info = MarkerProcessor.create_dtbook_element(marker)
                    if elem_info:
                        marker_elem = etree.SubElement(current_level1,
                                                       elem_info["tag"],
                                                       attrib=elem_info["attrs"])
                        marker_elem.text = elem_info["text"]

    # XML 파일 저장
    dtbook_filepath = os.path.join(output_dir, "dtbook.xml")
    tree = etree.ElementTree(dtbook_root)

    # XML 선언에 인코딩 명시적 지정
    with open(dtbook_filepath, 'wb') as f:
        # XML 선언
        f.write('<?xml version="1.0" encoding="utf-8" standalone="no"?>\n'.encode('utf-8'))
        # DTD 선언
        f.write('<!DOCTYPE dtbook PUBLIC "-//NISO//DTD dtbook 2005-3//EN" "http://www.daisy.org/z3986/2005/dtbook-2005-3.dtd">\n'.encode('utf-8'))
        # XML 트리 저장 - 명시적으로 인코딩 지정
        tree.write(f,
                  encoding='utf-8',
                  pretty_print=True,
                  xml_declaration=False,
                  method='xml')

    print(f"DTBook 생성 완료: {dtbook_filepath}")

    # --- 2. OPF 파일 생성 (dtbook.opf) ---
    print("OPF 생성 중...")
    opf_ns = "http://openebook.org/namespaces/oeb-package/1.0/"
    dc_ns = "http://purl.org/dc/elements/1.1/"

    opf_root = etree.Element(
        "package",
        attrib={
            "unique-identifier": "uid"
        },
        nsmap={
            None: opf_ns
        }
    )
 
    # 메타데이터
    metadata = etree.SubElement(opf_root, "metadata")

    # DC 메타데이터
    dc_metadata = etree.SubElement(metadata, "dc-metadata")

    format_elem = etree.SubElement(
        dc_metadata, "{%s}Format" % dc_ns, nsmap={'dc': dc_ns})
    format_elem.text = "ANSI/NISO Z39.86-2005"

    lang_elem = etree.SubElement(
        dc_metadata, "{%s}Language" % dc_ns, nsmap={'dc': dc_ns})
    lang_elem.text = book_language

    date_elem = etree.SubElement(
        dc_metadata, "{%s}Date" % dc_ns, nsmap={'dc': dc_ns})
    date_elem.text = datetime.now().strftime("%Y-%m-%d")

    # publisher_elem = etree.SubElement(
    #     dc_metadata, "{%s}Publisher" % dc_ns, nsmap={'dc': dc_ns})
    # publisher_elem.text = book_publisher

    title_elem = etree.SubElement(
        dc_metadata, "{%s}Title" % dc_ns, nsmap={'dc': dc_ns})
    title_elem.text = book_title

    identifier_elem = etree.SubElement(
        dc_metadata, "{%s}Identifier" % dc_ns, nsmap={'dc': dc_ns}, id="uid")
    identifier_elem.text = book_uid

    creator_elem = etree.SubElement(
        dc_metadata, "{%s}Creator" % dc_ns, nsmap={'dc': dc_ns})
    creator_elem.text = book_author

    # X-Metadata
    x_metadata = etree.SubElement(metadata, "x-metadata")
    etree.SubElement(x_metadata, "meta",
                     name="dtb:multimediaType",
                     content="textNCX")
    etree.SubElement(x_metadata, "meta",
                     name="dtb:totalTime",
                     content="0:00:00")
    etree.SubElement(x_metadata, "meta",
                     name="dtb:multimediaContent",
                     content="text")

    # Manifest
    manifest = etree.SubElement(opf_root, "manifest")

    # OPF
    etree.SubElement(manifest, "item",
                     href="dtbook.opf",
                     id="opf",
                     **{"media-type": "text/xml"})

    # DTBook
    etree.SubElement(manifest, "item",
                     href="dtbook.xml",
                     id="opf-1",
                     **{"media-type": "application/x-dtbook+xml"})

    # SMIL 파일들
    etree.SubElement(manifest, "item",
                     href="dtbook.smil",
                     id="mo",
                     **{"media-type": "application/smil"})

    # NCX
    etree.SubElement(manifest, "item",
                     href="dtbook.ncx",
                     id="ncx",
                     **{"media-type": "application/x-dtbncx+xml"})

    # Resources
    etree.SubElement(manifest, "item",
                     href="dtbook.res",
                     id="resource",
                     **{"media-type": "application/x-dtbresource+xml"})

    # Spine
    spine = etree.SubElement(opf_root, "spine")
    etree.SubElement(spine, "itemref",
                     idref="mo")

    # OPF Manifest에 이미지 파일 추가
    for item in content_structure:
        if item["type"] == "image":
            image_filename = os.path.basename(item["src"])
            image_id = f"img_{item['id']}"
            extension = os.path.splitext(image_filename)[1][1:].lower()

            # 이미지 확장자에 따른 MIME 타입 설정
            mime_type = {
                'jpg': 'image/jpeg',
                'jpeg': 'image/jpeg',
                'png': 'image/png',
                'gif': 'image/gif',
                'bmp': 'image/bmp',
                'tiff': 'image/tiff',
                'tif': 'image/tiff'
            }.get(extension, f'image/{extension}')

            print(f"이미지 매니페스트 추가: {image_filename} (MIME: {mime_type})")
            etree.SubElement(manifest, "item",
                             href=item["src"],
                             id=image_id,
                             **{"media-type": mime_type})

    # OPF 파일 저장
    opf_filepath = os.path.join(output_dir, "dtbook.opf")
    tree = etree.ElementTree(opf_root)

    with open(opf_filepath, 'wb') as f:
        f.write('<?xml version="1.0" encoding="utf-8" standalone="no"?>\n'.encode('utf-8'))
        f.write('<!DOCTYPE package PUBLIC "+//ISBN 0-9673008-1-9//DTD OEB 1.2 Package//EN" "http://openebook.org/dtds/oeb-1.2/oebpkg12.dtd">\n'.encode('utf-8'))
        tree.write(f,
                  encoding='utf-8',
                  pretty_print=True,
                  xml_declaration=False,
                  method='xml')

    print(f"OPF 생성 완료: {opf_filepath}")

    # --- 3. SMIL 파일 생성 (dtbook.smil) ---
    print("SMIL 파일 생성 중...")

    smil_ns = "http://www.w3.org/2001/SMIL20/"

    smil_root = etree.Element(
        "smil",
        nsmap={
            None: smil_ns
        }
    )

    # head
    head = etree.SubElement(smil_root, "head")
    etree.SubElement(head, "meta",
                     name="dtb:uid",
                     content=book_uid)
    etree.SubElement(head, "meta",
                     name="dtb:totalElapsedTime",
                     content="0:00:00")
    etree.SubElement(head, "meta",
                     name="dtb:generator",
                     content="DAISY Pipeline 2")

    # 페이지 관련 메타데이터 추가
    etree.SubElement(head, "meta",
                     name="dtb:totalPageCount",
                     content=str(total_pages))
    etree.SubElement(head, "meta",
                     name="dtb:maxPageNumber",
                     content=str(max_page_number))

    # body
    body = etree.SubElement(smil_root, "body")
    root_seq = etree.SubElement(body, "seq", id="root-seq")

    # doctitle과 docauthor 추가
    doctitle_par = etree.SubElement(root_seq, "par",
                                   id="sforsmil-1",
                                   **{"class": "doctitle"})
    etree.SubElement(doctitle_par, "text",
                     src="dtbook.xml#forsmil-1")

    docauthor_par = etree.SubElement(root_seq, "par",
                                    id="sforsmil-2",
                                    **{"class": "docauthor"})
    etree.SubElement(docauthor_par, "text",
                     src="dtbook.xml#forsmil-2")

    # 나머지 콘텐츠 추가
    for item in content_structure:
        # 페이지 마커 처리
        for marker in item.get("markers", []):
            if marker.type == "page":
                page_par = etree.SubElement(root_seq, "par",
                                          id=f"smil_par_page_{marker.value}_{marker.value}",
                                          **{"class": "pagenum"},
                                          customTest="pagenum")
                etree.SubElement(page_par, "text",
                               src=f"dtbook.xml#page_{marker.value}_{marker.value}")

        # 기본 콘텐츠
        if item["type"].startswith("h"):
            # 제목 요소일 경우 level로 처리
            level = int(item["type"][1])  # h1 -> 1, h2 -> 2, h3 -> 3, h4 -> 4, h5 -> 5, h6 -> 6
            par = etree.SubElement(root_seq, "par",
                                 id=f"smil_par_{item['id']}",
                                 **{"class": f"level{level}"})
            etree.SubElement(par, "text",
                           src=f"dtbook.xml#{item['id']}")
        else:
            # 일반 콘텐츠 처리
            par = etree.SubElement(root_seq, "par",
                                 id=f"smil_par_{item['id']}",
                                 **{"class": item["type"]})
            etree.SubElement(par, "text",
                           src=f"dtbook.xml#{item['id']}")

        # 표 처리
        if item["type"] == "table":
            for row_idx, row_data in enumerate(item["table_data"]["rows"]):
                for col_idx, cell_text in enumerate(row_data):
                    cell_par = etree.SubElement(root_seq, "par",
                                              id=f"smil_par_{item['id']}_cell_{row_idx}_{col_idx}",
                                              **{"class": "table-cell"})
                    etree.SubElement(cell_par, "text",
                                   src=f"dtbook.xml#table_{item['id']}_cell_{row_idx}_{col_idx}")

        # 마커 처리
        for marker in item.get("markers", []):
            if marker.type != "page":  # 페이지 마커는 이미 처리됨
                elem_info = MarkerProcessor.create_smil_element(marker, item["id"])
                if elem_info:
                    marker_par = etree.SubElement(root_seq, "par",
                                                id=f"smil_par_{item['id']}_{marker.type}",
                                                **{"class": elem_info["par_class"]})
                    etree.SubElement(marker_par, "text",
                                   src=elem_info["text_src"])

    # SMIL 파일 저장
    smil_filepath = os.path.join(output_dir, "dtbook.smil")
    tree = etree.ElementTree(smil_root)

    with open(smil_filepath, 'wb') as f:
        f.write('<?xml version="1.0" encoding="utf-8" standalone="no"?>\n'.encode('utf-8'))
        f.write('<!DOCTYPE smil PUBLIC "-//NISO//DTD dtbsmil 2005-2//EN" "http://www.daisy.org/z3986/2005/dtbsmil-2005-2.dtd">\n'.encode('utf-8'))
        tree.write(f,
                  encoding='utf-8',
                  pretty_print=True,
                  xml_declaration=False,
                  method='xml')

    print(f"SMIL 파일 생성 완료: {smil_filepath}")

    # --- 4. NCX 파일 생성 (dtbook.ncx) ---
    print("NCX 생성 중...")
    ncx_ns = "http://www.daisy.org/z3986/2005/ncx/"

    ncx_root = etree.Element(
        "{%s}ncx" % ncx_ns,
        attrib={
            "version": "2005-1"
        },
        nsmap={
            None: ncx_ns
        }
    )

    # head
    head = etree.SubElement(ncx_root, "head")
    etree.SubElement(head, "meta",
                     name="dc:Identifier",
                     content=book_uid)
    etree.SubElement(head, "meta",
                     name="dc:Title",
                     content=book_title)
    etree.SubElement(head, "meta",
                     name="dc:Date",
                     content=datetime.now().strftime("%Y-%m-%d"))
    etree.SubElement(head, "meta",
                     name="dc:Format",
                     content="ANSI/NISO Z39.86-2005")
    etree.SubElement(head, "meta",
                     name="dc:Language",
                     content=book_language)
    etree.SubElement(head, "meta",
                     name="dtb:depth",
                     content="3")  # 최대 제목 레벨
    etree.SubElement(head, "meta",
                     name="dtb:totalPageCount",
                     content=str(total_pages))
    etree.SubElement(head, "meta",
                     name="dtb:maxPageNumber",
                     content=str(max_page_number))
    etree.SubElement(head, "meta",
                     name="dtb:uid",
                     content=book_uid)
    etree.SubElement(head, "meta",
                     name="dtb:generator",
                     content="docx_to_daisy")

    # smilCustomTest 추가
    etree.SubElement(head, "smilCustomTest",
                    id="pagenum",
                    defaultState="false",
                    override="visible",
                    bookStruct="PAGE_NUMBER")
    etree.SubElement(head, "smilCustomTest",
                    id="note",
                    defaultState="true",
                    override="visible",
                    bookStruct="NOTE")
    etree.SubElement(head, "smilCustomTest",
                    id="noteref",
                    defaultState="true",
                    override="visible",
                    bookStruct="NOTE_REFERENCE")
    etree.SubElement(head, "smilCustomTest",
                    id="table",
                    defaultState="true",
                    override="visible")

    # docTitle
    doc_title = etree.SubElement(ncx_root, "docTitle")
    text = etree.SubElement(doc_title, "text")
    text.text = book_title

    # docAuthor
    doc_author = etree.SubElement(ncx_root, "docAuthor")
    text = etree.SubElement(doc_author, "text")
    text.text = book_author

    # navMap
    nav_map = etree.SubElement(ncx_root, "navMap")

    # 목차 항목 생성
    play_order = 1
    current_level1_point = None
    current_level2_point = None
    current_level3_point = None
    current_level4_point = None
    current_level5_point = None

    for item in content_structure:
        if item["type"].startswith("h"):
            level = int(item["type"][1])  # h1 -> 1, h2 -> 2, h3 -> 3, h4 -> 4, h5 -> 5, h6 -> 6
            nav_point = etree.Element("navPoint",
                                     id=f"ncx_{item['id']}",
                                     **{"class": f"level{level}"},
                                     playOrder=str(play_order))
            nav_label = etree.SubElement(nav_point, "navLabel")
            text = etree.SubElement(nav_label, "text")
            text.text = item["text"]
            content = etree.SubElement(nav_point, "content",
                                       src=f"dtbook.smil#smil_par_{item['id']}")

            # 계층 구조에 맞게 배치
            if level == 1:
                nav_map.append(nav_point)
                current_level1_point = nav_point
                current_level2_point = None
                current_level3_point = None
                current_level4_point = None
                current_level5_point = None
            elif level == 2 and current_level1_point is not None:
                current_level1_point.append(nav_point)
                current_level2_point = nav_point
                current_level3_point = None
                current_level4_point = None
                current_level5_point = None
            elif level == 3 and current_level2_point is not None:
                current_level2_point.append(nav_point)
                current_level3_point = nav_point
                current_level4_point = None
                current_level5_point = None
            elif level == 4 and current_level3_point is not None:
                current_level3_point.append(nav_point)
                current_level4_point = nav_point
                current_level5_point = None
            elif level == 5 and current_level4_point is not None:
                current_level4_point.append(nav_point)
                current_level5_point = nav_point
            elif level == 6 and current_level5_point is not None:
                current_level5_point.append(nav_point)

            play_order += 1
        elif item["type"] == "table":
            # 표 네비게이션 포인트 추가
            nav_point = etree.Element("navPoint",
                                     id=f"ncx_{item['id']}",
                                     **{"class": "level1"},
                                     playOrder=str(play_order))
            nav_label = etree.SubElement(nav_point, "navLabel")
            text = etree.SubElement(nav_label, "text")
            text.text = f"표 {play_order}"  # 표 제목 또는 번호
            content = etree.SubElement(nav_point, "content",
                                       src=f"dtbook.smil#smil_par_{item['id']}")
            
            # 현재 레벨에 추가
            if current_level1_point is not None:
                current_level1_point.append(nav_point)
            else:
                nav_map.append(nav_point)
            
            play_order += 1

    # pageList (페이지 마커가 있는 경우 추가)
    page_targets = []
    for item in content_structure:
        for marker in item.get("markers", []):
            if marker.type == "page":
                page_targets.append({
                    "id": f"p{marker.value}",
                    "value": marker.value,
                    "type": "normal",  # front, normal, special 중 하나
                    "smil_file": item["smil_file"],
                    "item_id": item["id"],
                    "play_order": play_order
                })
                play_order += 1

    if page_targets:
        page_list = etree.SubElement(ncx_root, "pageList", id="pages")
        nav_label = etree.SubElement(page_list, "navLabel")
        text = etree.SubElement(nav_label, "text")
        text.text = "Page numbers list"
        
        for page in page_targets:
            nav_point = etree.SubElement(page_list, "pageTarget",
                                        id=page["id"],
                                        **{"class": "pagenum"},
                                        type=page["type"],
                                        value=page["value"],
                                        playOrder=str(page["play_order"]))
            nav_label = etree.SubElement(nav_point, "navLabel")
            text = etree.SubElement(nav_label, "text")
            text.text = page["value"]
            content = etree.SubElement(nav_point, "content",
                                      src=f"{page['smil_file']}#smil_par_page_{page['value']}_{page['value']}")

    # navList (각주, 미주 등이 있는 경우 추가)
    note_targets = []
    for item in content_structure:
        for marker in item.get("markers", []):
            if marker.type in ["note", "annotation"]:
                note_targets.append({
                    "id": f"note_{marker.value}",
                    "text": marker.text,
                    "smil_file": item["smil_file"],
                    "item_id": item["id"],
                    "play_order": play_order
                })
                play_order += 1

    if note_targets:
        nav_list = etree.SubElement(ncx_root, "navList")
        nav_label = etree.SubElement(nav_list, "navLabel")
        text = etree.SubElement(nav_label, "text")
        text.text = "각주"

        for note in note_targets:
            nav_target = etree.SubElement(nav_list, "navTarget",
                                         id=note["id"],
                                         playOrder=str(note["play_order"]))
            nav_label = etree.SubElement(nav_target, "navLabel")
            text = etree.SubElement(nav_label, "text")
            text.text = note["text"]
            content = etree.SubElement(nav_target, "content",
                                      src=f"{note['smil_file']}#s{note['item_id']}")

    # NCX 파일 저장
    ncx_filepath = os.path.join(output_dir, "dtbook.ncx")
    tree = etree.ElementTree(ncx_root)

    with open(ncx_filepath, 'wb') as f:
        f.write(b'<?xml version="1.0" encoding="UTF-8"?>\n')
        f.write(b'<!DOCTYPE ncx PUBLIC "-//NISO//DTD ncx 2005-1//EN" "http://www.daisy.org/z3986/2005/ncx-2005-1.dtd" >\n')
        tree.write(f,
                   pretty_print=True,
                   encoding='utf-8',
                   xml_declaration=False)

    print(f"NCX 생성 완료: {ncx_filepath}")

    # --- 5. Resources 파일 생성 (dtbook.res) ---
    print("Resources 생성 중...")
    res_ns = "http://www.daisy.org/z3986/2005/resource/"

    res_root = etree.Element(
        "{%s}resources" % res_ns,
        attrib={
            "version": "2005-1"
        },
        nsmap={
            None: res_ns
        }
    )

    # NCX scope
    ncx_scope = etree.SubElement(res_root, "scope",
                                 nsuri="http://www.daisy.org/z3986/2005/ncx/")

    # Custom tests
    custom_tests = [
        ("page-set", "PAGE_NUMBER", "page"),
        ("note-set", "NOTE", "note"),
        ("notref-set", "NOTE_REFERENCE", "note"),
        ("annot-set", "ANNOTATION", "annotation"),
        ("line-set", "LINE_NUMBER", "line"),
        ("sidebar-set", "OPTIONAL_SIDEBAR", "sidebar"),
        ("prodnote-set", "OPTIONAL_PRODUCER_NOTE", "note")
    ]

    for test_id, book_struct, text in custom_tests:
        node_set = etree.SubElement(ncx_scope, "nodeSet",
                                    id=test_id,
                                    select=f"//smilCustomTest[@bookStruct='{book_struct}']")
        resource = etree.SubElement(node_set, "resource",
                                    **{"{http://www.w3.org/XML/1998/namespace}lang": "en"})
        text_elem = etree.SubElement(resource, "text")
        text_elem.text = text

    # SMIL scope
    smil_scope = etree.SubElement(res_root, "scope",
                                  nsuri="http://www.w3.org/2001/SMIL20/")

    # Math sets
    math_sets = [
        ("math-seq-set", "seq", "mathematical formula"),
        ("math-par-set", "par", "mathematical formula")
    ]

    for set_id, elem_type, text in math_sets:
        node_set = etree.SubElement(smil_scope, "nodeSet",
                                    id=set_id,
                                    select=f"//{elem_type}[@class='math']")
        resource = etree.SubElement(node_set, "resource",
                                    **{"{http://www.w3.org/XML/1998/namespace}lang": "en"})
        text_elem = etree.SubElement(resource, "text")
        text_elem.text = text

    # Resources 파일 저장
    res_filepath = os.path.join(output_dir, "dtbook.res")
    tree = etree.ElementTree(res_root)

    with open(res_filepath, 'wb') as f:
        f.write(b'<?xml version="1.0" encoding="utf-8"?>\n')
        f.write(b'<!DOCTYPE resources\n  PUBLIC "-//NISO//DTD resource 2005-1//EN" "http://www.daisy.org/z3986/2005/resource-2005-1.dtd">\n')
        tree.write(f,
                   pretty_print=True,
                   encoding='utf-8',
                   xml_declaration=False)

    print(f"Resources 생성 완료: {res_filepath}")

    print("\n--- DAISY 기본 파일 생성 완료 ---")
    print(f"생성된 파일은 '{output_dir}' 폴더에 있습니다.")
    print("주의: 이 코드는 DOCX의 기본적인 제목/문단 구조만 변환하며,")
    print("      오디오, SMIL 동기화, 목록, 표, 이미지, 페이지 번호 등은 포함하지 않습니다.")


def zip_daisy_output(source_dir, output_zip_filename):

    """
    지정된 폴더의 내용을 ZIP 파일로 압축합니다.

    Args:
        source_dir (str): 압축할 DAISY 파일들이 있는 폴더 경로.
        output_zip_filename (str): 생성될 ZIP 파일의 이름 (경로 포함 가능).
    """
    if not os.path.isdir(source_dir):
        print(f"오류: 소스 디렉토리를 찾을 수 없습니다 - {source_dir}")
        return

    try:
        print(f"'{source_dir}' 폴더를 '{output_zip_filename}' 파일로 압축 중...")
        # ZIP 파일 쓰기 모드로 열기 (압축 사용)
        with zipfile.ZipFile(output_zip_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
            # source_dir 내부의 모든 파일과 폴더를 순회
            for root, dirs, files in os.walk(source_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    # ZIP 파일 내부에 저장될 상대 경로 계산
                    # (source_dir 자체를 포함하지 않도록 함)
                    archive_name = os.path.relpath(file_path, source_dir)
                    print(f"  추가 중: {archive_name}")
                    zipf.write(file_path, arcname=archive_name)
        print(f"ZIP 파일 생성 완료: {output_zip_filename}")
    except Exception as e:
        print(f"ZIP 파일 생성 중 오류 발생: {e}")
