import zipfile
import os
import uuid
import argparse
import re
from docx import Document  # python-docx 라이브러리
from lxml import etree  # lxml 라이브러리
from datetime import datetime
from .markers import MarkerProcessor  # 마커 처리기 임포트


def split_text_to_words(text):
    """텍스트를 단어로 분리하는 함수
    
    Args:
        text (str): 분리할 텍스트
        
    Returns:
        list: 분리된 단어들의 리스트
    """
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
    # --- 기본 정보 설정 ---
    if book_title is None:
        book_title = os.path.splitext(os.path.basename(docx_file_path))[0]
    if book_author is None:
        book_author = "작성자"
    if book_publisher is None:
        book_publisher = "출판사"

    book_uid = f"AUTO-UID-{uuid.uuid4().int}-packaged"  # 고유 식별자

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

    content_structure = []
    element_counter = 0
    sent_counter = 0

    # 이미지 저장 디렉토리 생성
    images_dir = os.path.join(output_dir, "images")
    os.makedirs(images_dir, exist_ok=True)

    # 이미지 처리
    image_counter = 0
    print("\n이미지 처리 시작...")

    # 문서의 모든 이미지 관계와 위치 매핑
    image_locations = {}  # rId -> paragraph index 매핑
    for para_idx, para in enumerate(document.paragraphs):
        for run in para.runs:
            if hasattr(run, '_element') and run._element.find('.//a:blip', {'a': 'http://schemas.openxmlformats.org/drawingml/2006/main'}) is not None:
                blip = run._element.find(
                    './/a:blip', {'a': 'http://schemas.openxmlformats.org/drawingml/2006/main'})
                rId = blip.get(
                    '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed')
                if rId:
                    image_locations[rId] = para_idx

    # 문서의 모든 이미지 관계 처리
    print("\n1. 문서의 이미지 관계 확인 중...")
    for rel in document.part.rels.values():
        print(f"  관계 타입: {rel.reltype}")
        if "image" in rel.reltype:
            try:
                image_counter += 1
                element_counter += 1
                sent_counter += 1
                elem_id = f"id_{element_counter}"
                sent_id = f"id_{sent_counter}"

                # 이미지 파일 저장
                image_filename = f"image_{image_counter}{os.path.splitext(rel.target_part.partname)[1]}"
                image_path = os.path.join(images_dir, image_filename)

                print(f"  이미지 {image_counter} 발견:")
                print(f"    - 파일명: {image_filename}")
                print(f"    - 저장 경로: {image_path}")
                print(f"    - 관계 ID: {rel.rId}")

                with open(image_path, "wb") as f:
                    f.write(rel.target_part.blob)

                # 이미지 설명 찾기
                alt_text = f"이미지 {image_counter}"

                # 이미지의 위치 찾기
                para_idx = image_locations.get(
                    rel.rId, len(document.paragraphs))

                content_structure.append({
                    "type": "imggroup",
                    "image_src": f"images/{image_filename}",
                    "alt_text": alt_text,
                    "id": elem_id,
                    "sent_id": sent_id,
                    "level": 0,
                    "markers": [],
                    "smil_file": "mo.smil",
                    "position": para_idx,
                    "insert_before": True  # 단락 앞에 이미지 삽입
                })

                print(f"    - 이미지 위치: 단락 {para_idx}")
                print(f"    - 이미지 추출 완료")
            except Exception as e:
                print(f"    - 오류 발생: {str(e)}")

    print(f"\n총 {image_counter}개의 이미지 처리 완료")
    print("이미지 처리 종료\n")

    # DOCX의 단락(paragraph)을 순회하며 구조 파악
    print("DOCX 파일 분석 중...")
    for para_idx, para in enumerate(document.paragraphs):
        text = para.text.strip()

        # 마커 처리
        processed_text, markers = MarkerProcessor.process_text(text)

        # 페이지 마커가 있는 경우 별도의 요소로 추가
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
                    "smil_file": "mo.smil",
                    "position": para_idx,
                    "insert_before": True  # 단락 앞에 페이지 번호 삽입
                })

        if not processed_text.strip():  # 마커만 있고 실제 내용이 없는 경우 건너뜀
            continue

        element_counter += 1
        sent_counter += 1
        elem_id = f"id_{element_counter}"
        sent_id = f"id_{sent_counter}"
        style_name = para.style.name.lower()  # 스타일 이름을 소문자로 비교

        # 단어 분리
        words = split_text_to_words(processed_text)

        # 스타일 이름에 따른 구조 매핑
        content_structure.append({
            "type": "h1" if style_name.startswith('heading 1') or style_name == '제목 1' else
            "h2" if style_name.startswith('heading 2') or style_name == '제목 2' else
            "h3" if style_name.startswith('heading 3') or style_name == '제목 3' else
            "p",
            "text": processed_text,
            "words": words,
            "id": elem_id,
            "sent_id": sent_id,
            "level": 1 if style_name.startswith('heading 1') or style_name == '제목 1' else
                    2 if style_name.startswith('heading 2') or style_name == '제목 2' else
                    3 if style_name.startswith('heading 3') or style_name == '제목 3' else
                    0,
            "markers": markers,
            "smil_file": "mo.smil",
            "position": para_idx,
            "insert_before": False  # 일반 텍스트는 순서대로 삽입
        })

    # 콘텐츠를 위치에 따라 정렬
    content_structure.sort(key=lambda x: (
        x["position"], not x["insert_before"]))

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
    dtbook_book = etree.SubElement(dtbook_root, "book")

    # frontmatter 추가
    dtbook_frontmatter = etree.SubElement(dtbook_book, "frontmatter")

    # doctitle과 docauthor 추가 (단어 단위로 분리)
    doctitle = etree.SubElement(dtbook_frontmatter, "doctitle",
                                id="forsmil-1",
                                smilref="mo.smil#sforsmil-1")
    sent_counter += 1
    sent = etree.SubElement(doctitle, "sent",
                            id=f"id_{sent_counter}",
                            smilref=f"mo.smil#sid_{sent_counter}")
    for word in split_text_to_words(book_title):
        w = etree.SubElement(sent, "w")
        w.text = word

    docauthor = etree.SubElement(dtbook_frontmatter, "docauthor",
                                 id="forsmil-2",
                                 smilref="mo.smil#sforsmil-2")
    sent_counter += 1
    sent = etree.SubElement(docauthor, "sent",
                            id=f"id_{sent_counter}",
                            smilref=f"mo.smil#sid_{sent_counter}")
    for word in split_text_to_words(book_author):
        w = etree.SubElement(sent, "w")
        w.text = word

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
                id=item["id"],
                page=str(item["text"])
            )
            pagenum.text = str(item["text"])
            continue
        elif item["type"] == "imggroup":
            # 이미지는 현재 문서 구조의 적절한 레벨에 추가
            if current_level1 is None:
                # level1이 없는 경우 생성
                current_level1 = etree.SubElement(dtbook_bodymatter, "level1")
                current_level = 1
                # 임시 제목 추가
                temp_h1 = etree.SubElement(current_level1, "h1")
                temp_h1.text = "제목 없음"

            # 현재 레벨에 따라 적절한 부모 요소 찾기
            if current_level == 0 or current_level == 1:
                parent = current_level1
            else:
                # level2, level3의 경우 현재 레벨에 맞는 부모 찾기
                parent = current_level1
                for l in range(2, current_level + 1):
                    level_elem = parent.find(f"level{l}")
                    if level_elem is not None:
                        parent = level_elem

            imggroup = etree.SubElement(
                parent,
                "imggroup",
                id=item["id"]
            )
            img = etree.SubElement(imggroup, "img",
                                   id=f"{item['id']}_img",
                                   src=item["image_src"],
                                   alt=item["alt_text"])
            caption = etree.SubElement(imggroup, "caption",
                                       id=f"{item['id']}_caption")
            sent = etree.SubElement(caption, "sent",
                                    id=item["sent_id"],
                                    smilref=f"{item['smil_file']}#s{item['sent_id']}")
            w = etree.SubElement(sent, "w")
            w.text = item["alt_text"]
            continue

        if item["type"].startswith("h"):
            level = int(item["type"][1])  # h1 -> 1, h2 -> 2, h3 -> 3

            if level == 1:
                # 새로운 level1 시작
                current_level1 = etree.SubElement(dtbook_bodymatter, "level1")
                current_level = 1
                heading = etree.SubElement(current_level1, "h1",
                                           id=item["id"],
                                           smilref=f"{item['smil_file']}#s{item['id']}")
                sent = etree.SubElement(heading, "sent",
                                        id=item["sent_id"],
                                        smilref=f"{item['smil_file']}#s{item['sent_id']}")
                for word in item["words"]:
                    w = etree.SubElement(sent, "w")
                    w.text = word
            else:
                # level2, level3는 이전 level1 내에 위치
                if current_level1 is None:
                    # level1이 없는 경우 생성
                    current_level1 = etree.SubElement(
                        dtbook_bodymatter, "level1")
                    current_level = 1
                    # 임시 제목 추가
                    temp_h1 = etree.SubElement(current_level1, "h1")
                    temp_h1.text = "제목 없음"

                parent = current_level1
                for l in range(2, level + 1):
                    level_elem = parent.find(f"level{l}")
                    if level_elem is None:
                        level_elem = etree.SubElement(parent, f"level{l}")
                    parent = level_elem

                heading = etree.SubElement(parent, f"h{level}",
                                           id=item["id"],
                                           smilref=f"{item['smil_file']}#s{item['id']}")
                sent = etree.SubElement(heading, "sent",
                                        id=item["sent_id"],
                                        smilref=f"{item['smil_file']}#s{item['sent_id']}")
                for word in item["words"]:
                    w = etree.SubElement(sent, "w")
                    w.text = word

            # 기타 마커 처리
            for marker in item.get("markers", []):
                if marker.type != "page":  # 페이지 마커는 이미 처리됨
                    elem_info = MarkerProcessor.create_dtbook_element(marker)
                    if elem_info:
                        marker_elem = etree.SubElement(parent, elem_info["tag"],
                                                       attrib=elem_info["attrs"])
                        marker_elem.text = elem_info["text"]
        else:
            # 일반 단락은 현재 level 요소 내에 추가
            if current_level1 is None:
                # level1이 없는 경우 생성
                current_level1 = etree.SubElement(dtbook_bodymatter, "level1")
                # 임시 제목 추가
                temp_h1 = etree.SubElement(current_level1, "h1")
                temp_h1.text = "제목 없음"

            p = etree.SubElement(current_level1, "p",
                                 id=item["id"],
                                 smilref=f"{item['smil_file']}#s{item['id']}")
            sent = etree.SubElement(p, "sent",
                                    id=item["sent_id"],
                                    smilref=f"{item['smil_file']}#s{item['sent_id']}")
            for word in item["words"]:
                w = etree.SubElement(sent, "w")
                w.text = word

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

    with open(dtbook_filepath, 'wb') as f:
        f.write(b'<?xml version="1.0" encoding="utf-8"?>\n')
        f.write(b'<!DOCTYPE dtbook\n  PUBLIC "-//NISO//DTD dtbook 2005-3//EN" "http://www.daisy.org/z3986/2005/dtbook-2005-3.dtd">\n')
        tree.write(f,
                   pretty_print=True,
                   encoding='utf-8',
                   xml_declaration=False)

    print(f"DTBook 생성 완료: {dtbook_filepath}")

    # --- 2. OPF 파일 생성 (book.opf) ---
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

    publisher_elem = etree.SubElement(
        dc_metadata, "{%s}Publisher" % dc_ns, nsmap={'dc': dc_ns})
    publisher_elem.text = book_publisher

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
                     href="book.opf",
                     id="opf",
                     **{"media-type": "text/xml"})

    # DTBook
    etree.SubElement(manifest, "item",
                     href="dtbook.xml",
                     id="opf-1",
                     **{"media-type": "application/x-dtbook+xml"})

    # SMIL 파일들
    etree.SubElement(manifest, "item",
                     href="mo.smil",
                     id="mo",
                     **{"media-type": "application/smil"})

    # NCX
    etree.SubElement(manifest, "item",
                     href="navigation.ncx",
                     id="ncx",
                     **{"media-type": "application/x-dtbncx+xml"})

    # Resources
    etree.SubElement(manifest, "item",
                     href="resources.res",
                     id="resource",
                     **{"media-type": "application/x-dtbresource+xml"})

    # Spine
    spine = etree.SubElement(opf_root, "spine")
    etree.SubElement(spine, "itemref",
                     idref="mo")

    # OPF Manifest에 이미지 파일 추가
    for item in content_structure:
        if item["type"] == "imggroup":
            image_filename = os.path.basename(item["image_src"])
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
                             href=item["image_src"],
                             id=image_id,
                             **{"media-type": mime_type})

    # OPF 파일 저장
    opf_filepath = os.path.join(output_dir, "book.opf")
    tree = etree.ElementTree(opf_root)

    with open(opf_filepath, 'wb') as f:
        f.write(b'<?xml version="1.0" encoding="utf-8"?>\n')
        f.write(b'<!DOCTYPE package\n  PUBLIC "+//ISBN 0-9673008-1-9//DTD OEB 1.2 Package//EN" "http://openebook.org/dtds/oeb-1.2/oebpkg12.dtd">\n')
        tree.write(f,
                   pretty_print=True,
                   encoding='utf-8',
                   xml_declaration=False)

    print(f"OPF 생성 완료: {opf_filepath}")

    # --- 3. SMIL 파일 생성 (mo.smil) ---
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
    doctitle_seq = etree.SubElement(root_seq, "seq",
                                    id="sforsmil-1",
                                    **{"class": "doctitle"})
    doctitle_par = etree.SubElement(doctitle_seq, "par",
                                    id=f"sid_{sent_counter-1}",
                                    **{"class": "sent"})
    etree.SubElement(doctitle_par, "text",
                     src=f"dtbook.xml#id_{sent_counter-1}")

    docauthor_seq = etree.SubElement(root_seq, "seq",
                                     id="sforsmil-2",
                                     **{"class": "docauthor"})
    docauthor_par = etree.SubElement(docauthor_seq, "par",
                                     id=f"sid_{sent_counter}",
                                     **{"class": "sent"})
    etree.SubElement(docauthor_par, "text",
                     src=f"dtbook.xml#id_{sent_counter}")

    # 나머지 콘텐츠 추가
    for item in content_structure:
        # 페이지 마커 처리
        for marker in item.get("markers", []):
            if marker.type == "page":
                page_seq = etree.SubElement(root_seq, "seq",
                                            id=f"spage_{marker.value}",
                                            **{"class": "pagenum"})
                page_par = etree.SubElement(page_seq, "par",
                                            id=f"ppage_{marker.value}")
                etree.SubElement(page_par, "text",
                                 src=f"dtbook.xml#page_{marker.value}")

        seq = etree.SubElement(root_seq, "seq",
                               id=f"s{item['id']}",
                               **{"class": item["type"]})

        # 기본 콘텐츠
        par = etree.SubElement(seq, "par",
                               id=f"s{item['sent_id']}",
                               **{"class": "sent"})
        etree.SubElement(par, "text",
                         src=f"dtbook.xml#{item['sent_id']}")

        # 마커에 대한 SMIL 요소 추가
        for marker in item.get("markers", []):
            elem_info = MarkerProcessor.create_smil_element(marker, item["id"])
            if elem_info:
                marker_seq = etree.SubElement(seq, "seq",
                                              **{"class": elem_info["seq_class"]})
                marker_par = etree.SubElement(marker_seq, "par",
                                              **{"class": elem_info["par_class"]})
                etree.SubElement(marker_par, "text",
                                 src=elem_info["text_src"])

    # SMIL 파일 저장
    smil_filepath = os.path.join(output_dir, "mo.smil")
    tree = etree.ElementTree(smil_root)

    with open(smil_filepath, 'wb') as f:
        f.write(b'<?xml version="1.0" encoding="utf-8"?>\n')
        f.write(b'<!DOCTYPE smil\n  PUBLIC "-//NISO//DTD dtbsmil 2005-2//EN" "http://www.daisy.org/z3986/2005/dtbsmil-2005-2.dtd">\n')
        tree.write(f,
                   pretty_print=True,
                   encoding='utf-8',
                   xml_declaration=False)

    print(f"SMIL 파일 생성 완료: {smil_filepath}")

    # --- 4. NCX 파일 생성 (navigation.ncx) ---
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
                     name="dtb:uid",
                     content=book_uid)
    etree.SubElement(head, "meta",
                     name="dtb:depth",
                     content="3")  # 최대 제목 레벨
    etree.SubElement(head, "meta",
                     name="dtb:totalPageCount",
                     content=str(total_pages))
    etree.SubElement(head, "meta",
                     name="dtb:maxPageNumber",
                     content=str(max_page_number))

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

    for item in content_structure:
        if item["type"].startswith("h"):
            level = int(item["type"][1])  # h1 -> 1, h2 -> 2, h3 -> 3
            nav_point = etree.Element("navPoint",
                                      id=f"nav_{item['id']}",
                                      playOrder=str(play_order))
            nav_label = etree.SubElement(nav_point, "navLabel")
            text = etree.SubElement(nav_label, "text")
            text.text = item["text"]
            content = etree.SubElement(nav_point, "content",
                                       src=f"{item['smil_file']}#s{item['id']}")

            if level == 1:
                nav_map.append(nav_point)
                current_level1_point = nav_point
                current_level2_point = None
            elif level == 2 and current_level1_point is not None:
                current_level1_point.append(nav_point)
                current_level2_point = nav_point
            elif level == 3 and current_level2_point is not None:
                current_level2_point.append(nav_point)

            play_order += 1

    # pageList (페이지 마커가 있는 경우 추가)
    page_targets = []
    for item in content_structure:
        for marker in item.get("markers", []):
            if marker.type == "page":
                page_targets.append({
                    "id": f"page_{marker.value}",
                    "value": marker.value,
                    "type": "normal",  # front, normal, special 중 하나
                    "smil_file": item["smil_file"],
                    "item_id": item["id"]
                })

    if page_targets:
        page_list = etree.SubElement(ncx_root, "pageList")
        for page in page_targets:
            nav_point = etree.SubElement(page_list, "pageTarget",
                                         id=page["id"],
                                         value=page["value"],
                                         type=page["type"])
            nav_label = etree.SubElement(nav_point, "navLabel")
            text = etree.SubElement(nav_label, "text")
            text.text = page["value"]
            content = etree.SubElement(nav_point, "content",
                                       src=f"{page['smil_file']}#s{page['item_id']}")

    # navList (각주, 미주 등이 있는 경우 추가)
    note_targets = []
    for item in content_structure:
        for marker in item.get("markers", []):
            if marker.type in ["note", "annotation"]:
                note_targets.append({
                    "id": f"note_{marker.value}",
                    "text": marker.text,
                    "smil_file": item["smil_file"],
                    "item_id": item["id"]
                })

    if note_targets:
        nav_list = etree.SubElement(ncx_root, "navList")
        nav_label = etree.SubElement(nav_list, "navLabel")
        text = etree.SubElement(nav_label, "text")
        text.text = "각주"

        for note in note_targets:
            nav_target = etree.SubElement(nav_list, "navTarget",
                                          id=note["id"])
            nav_label = etree.SubElement(nav_target, "navLabel")
            text = etree.SubElement(nav_label, "text")
            text.text = note["text"]
            content = etree.SubElement(nav_target, "content",
                                       src=f"{note['smil_file']}#s{note['item_id']}")

    # NCX 파일 저장
    ncx_filepath = os.path.join(output_dir, "navigation.ncx")
    tree = etree.ElementTree(ncx_root)

    with open(ncx_filepath, 'wb') as f:
        f.write(b'<?xml version="1.0" encoding="utf-8"?>\n')
        f.write(b'<!DOCTYPE ncx\n  PUBLIC "-//NISO//DTD ncx 2005-1//EN" "http://www.daisy.org/z3986/2005/ncx-2005-1.dtd">\n')
        tree.write(f,
                   pretty_print=True,
                   encoding='utf-8',
                   xml_declaration=False)

    print(f"NCX 생성 완료: {ncx_filepath}")

    # --- 5. Resources 파일 생성 (resources.res) ---
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
    res_filepath = os.path.join(output_dir, "resources.res")
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


def main():
    parser = argparse.ArgumentParser(
        description='DOCX 파일을 DAISY 형식으로 변환합니다.')

    parser.add_argument('input_file',
                        help='변환할 DOCX 파일 경로')

    parser.add_argument('-o', '--output-dir',
                        default='output_daisy_from_docx',
                        help='생성된 DAISY 파일을 저장할 폴더 (기본값: output_daisy_from_docx)')

    parser.add_argument('--title',
                        help='책 제목 (기본값: DOCX 파일명)')

    parser.add_argument('--author',
                        help='저자 (기본값: "작성자")')

    parser.add_argument('--publisher',
                        help='출판사 (기본값: "출판사")')

    parser.add_argument('--language',
                        default='ko',
                        help='언어 코드 (ISO 639-1) (기본값: ko)')

    parser.add_argument('--zip',
                        action='store_true',
                        help='DAISY 파일들을 ZIP 파일로 압축합니다')

    parser.add_argument('--zip-filename',
                        help='ZIP 파일 이름 (기본값: output_dir과 동일한 이름에 .zip 확장자)')

    args = parser.parse_args()

    # DAISY 파일 생성
    create_daisy_book(
        docx_file_path=args.input_file,
        output_dir=args.output_dir,
        book_title=args.title,
        book_author=args.author,
        book_publisher=args.publisher,
        book_language=args.language
    )

    # ZIP 파일 생성 (--zip 옵션이 지정된 경우)
    if args.zip:
        zip_filename = args.zip_filename
        if zip_filename is None:
            # 기본 ZIP 파일 이름: 출력 디렉토리 이름.zip
            zip_filename = f"{args.output_dir}.zip"
        zip_daisy_output(args.output_dir, zip_filename)


if __name__ == '__main__':
    main()
