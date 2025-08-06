import zipfile
import os
import uuid
import argparse
import re
import logging
import html
from lxml import etree
from datetime import datetime
import shutil
from docx_to_daisy.markers import MarkerProcessor
import gc

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def create_epub3_from_daisy(daisy_dir, output_dir, book_title=None, book_author=None, book_publisher=None, book_language="ko"):
    """DAISY 3.0 파일들을 EPUB 3.0 표준에 맞춰 변환합니다.
    
    EPUB 3.0 Core Media Types 지원:
    - Text: application/xhtml+xml
    - Images: image/jpeg, image/png, image/gif, image/svg+xml
    - Styles: text/css
    - Audio: audio/mpeg, audio/mp4 (optional)
    
    EPUB 3.0 표준 구조:
    - mimetype (첫 번째 파일, 압축 없음)
    - META-INF/container.xml
    - EPUB/package.opf (manifest에 모든 리소스 등록)
    - EPUB/nav.xhtml (navigation document)
    - EPUB/*.xhtml (content documents)
    - EPUB/*.jpg, *.png, *.gif, *.svg (이미지 파일들)

    Args:
        daisy_dir (str): DAISY 파일들이 있는 디렉토리 경로
        output_dir (str): 생성된 EPUB3 파일 저장 폴더
        book_title (str, optional): 책 제목. 기본값은 None (DAISY에서 추출)
        book_author (str, optional): 저자. 기본값은 None (DAISY에서 추출)
        book_publisher (str, optional): 출판사. 기본값은 None (DAISY에서 추출)
        book_language (str, optional): 언어 코드 (ISO 639-1). 기본값은 "ko"
        
    Returns:
        str: 생성된 EPUB 파일의 전체 경로
    """
    
    # --- 출력 디렉토리 생성 ---
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(os.path.join(output_dir, "EPUB"), exist_ok=True)
    os.makedirs(os.path.join(output_dir, "META-INF"), exist_ok=True)

    # --- DAISY 파일 읽기 ---
    dtbook_file = os.path.join(daisy_dir, "dtbook.xml")
    ncx_file = os.path.join(daisy_dir, "dtbook.ncx")
    smil_file = os.path.join(daisy_dir, "dtbook.smil")
    
    if not os.path.exists(dtbook_file):
        raise FileNotFoundError(f"DTBook 파일을 찾을 수 없습니다: {dtbook_file}")
    
    # DTBook XML 파싱
    dtbook_tree = etree.parse(dtbook_file)
    dtbook_root = dtbook_tree.getroot()
    
    # 네임스페이스 정의
    dtbook_ns = "http://www.daisy.org/z3986/2005/dtbook/"
    dc_ns = "http://purl.org/dc/elements/1.1/"
    
    # 메타데이터 추출
    head = dtbook_root.find(f"{{{dtbook_ns}}}head")
    if head is not None:
        # 기본 메타데이터 추출
        uid_elem = head.find(f"meta[@name='dtb:uid']")
        title_elem = head.find(f"meta[@name='dc:Title']")
        author_elem = head.find(f"meta[@name='dc:Creator']")
        publisher_elem = head.find(f"meta[@name='dc:Publisher']")
        language_elem = head.find(f"meta[@name='dc:Language']")
        
        book_uid = uid_elem.get("content") if uid_elem is not None else str(uuid.uuid4())
        book_title = book_title or (title_elem.get("content") if title_elem is not None else "Unknown Title")
        book_author = book_author or (author_elem.get("content") if author_elem is not None else "Unknown Author")
        book_publisher = book_publisher or (publisher_elem.get("content") if publisher_elem is not None else "Unknown Publisher")
        book_language = language_elem.get("content") if language_elem is not None else book_language
    
    print(f"책 제목: {book_title}")
    print(f"저자: {book_author}")
    print(f"출판사: {book_publisher}")
    print(f"언어: {book_language}")
    print(f"UID: {book_uid}")

    # --- 1. mimetype 파일 생성 ---
    print("mimetype 파일 생성 중...")
    mimetype_file = os.path.join(output_dir, "mimetype")
    with open(mimetype_file, 'w', encoding='utf-8') as f:
        f.write("application/epub+zip")
    
    # --- 2. container.xml 생성 ---
    print("container.xml 생성 중...")
    
    # 표준 EPUB container.xml 내용 (검증된 형식)
    container_xml_content = '''<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="EPUB/package.opf" media-type="application/oebps-package+xml" />
  </rootfiles>
</container>'''
    
    container_file = os.path.join(output_dir, "META-INF", "container.xml")
    with open(container_file, 'w', encoding='utf-8', newline='\n') as f:
        f.write(container_xml_content)

    # --- 3. 이미지 파일 복사 ---
    print("이미지 파일 복사 중...")
    epub_dir = os.path.join(output_dir, "EPUB")
    
    print(f"DAISY 루트 디렉토리: {daisy_dir}")
    print(f"EPUB 디렉토리: {epub_dir}")
    
    # DAISY 루트 디렉토리에서 이미지 파일 찾기
    if os.path.exists(daisy_dir):
        all_files = os.listdir(daisy_dir)
        image_files = [f for f in all_files if f.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.svg'))]
        print(f"DAISY에서 발견된 이미지 파일들: {image_files}")
        
        for image_file in image_files:
            src_path = os.path.join(daisy_dir, image_file)
            dst_path = os.path.join(epub_dir, image_file)
            
            try:
                shutil.copy2(src_path, dst_path)
                print(f"✅ EPUB Core Media Type 이미지 복사 성공: {image_file} (EPUB 폴더 직접)")
            except Exception as e:
                print(f"❌ 이미지 복사 실패: {image_file} - {e}")
    else:
        print(f"❌ DAISY 디렉토리가 존재하지 않습니다: {daisy_dir}")

    # --- 4. NCX 파일 파싱 및 구조 분석 ---
    print("NCX 파일 파싱 중...")
    
    if not os.path.exists(ncx_file):
        raise FileNotFoundError(f"NCX 파일을 찾을 수 없습니다: {ncx_file}")
    
    # NCX 파일 파싱
    ncx_tree = etree.parse(ncx_file)
    ncx_root = ncx_tree.getroot()
    
    # NCX 네임스페이스
    ncx_ns = "http://www.daisy.org/z3986/2005/ncx/"
    
    # navMap에서 navPoint들을 추출
    navmap = ncx_root.find(f"{{{ncx_ns}}}navMap")
    if navmap is None:
        raise ValueError("NCX에서 navMap을 찾을 수 없습니다.")
    
    nav_points = navmap.findall(f"{{{ncx_ns}}}navPoint")
    print(f"총 {len(nav_points)}개의 navPoint 발견")
    
    # --- 5. Title Page 생성 ---
    print("Title Page 생성 중...")
    
    # xhtml_files 리스트 초기화
    xhtml_files = []
    
    # Title Page XHTML 생성
    title_xhtml = create_title_page_xhtml(book_title, book_author, book_publisher, book_language)
    
    title_filename = "dtbook-1.xhtml"
    title_filepath = os.path.join(output_dir, "EPUB", title_filename)
    
    with open(title_filepath, 'w', encoding='utf-8') as f:
        f.write(title_xhtml)
    
    xhtml_files.append({
        'filename': title_filename,
        'filepath': title_filepath,
        'title': book_title,
        'nav_point': None
    })
    
    print(f"Title Page 생성: {title_filename}")
    
    # --- 6. DTBook 구조 분석 및 XHTML 파일 생성 ---
    print("DTBook 구조 분석 중...")
    
    # bodymatter 찾기
    book = dtbook_root.find(f"{{{dtbook_ns}}}book")
    bodymatter = book.find(f"{{{dtbook_ns}}}bodymatter") if book is not None else None
    
    if bodymatter is None:
        raise ValueError("DTBook에서 bodymatter를 찾을 수 없습니다.")
    
    # NCX 구조를 기반으로 XHTML 파일 생성
    current_file_index = 2  # title page 이후부터 시작
    
    for nav_point in nav_points:
        if nav_point.get('class') == 'level1':
            # level1 navPoint 처리
            nav_label = nav_point.find(f"{{{ncx_ns}}}navLabel")
            content = nav_point.find(f"{{{ncx_ns}}}content")
            
            if nav_label is not None and content is not None:
                title = nav_label.find(f"{{{ncx_ns}}}text").text if nav_label.find(f"{{{ncx_ns}}}text") is not None else f"Section {current_file_index}"
                content_src = content.get('src', '')
                
                # SMIL 파일에서 해당 ID 찾기
                smil_id = content_src.split('#')[-1] if '#' in content_src else ''
                
                # DTBook에서 해당 요소 찾기
                target_element = find_element_by_smil_id(bodymatter, smil_id, dtbook_ns)
                
                if target_element is not None:
                    # XHTML 파일 생성 (DTBook 구조 기반)
                    xhtml_content = create_xhtml_from_nav_structure(
                        target_element, current_file_index, 
                        title, dtbook_ns, book_title, book_language
                    )
                    
                    filename = f"dtbook-{current_file_index}.xhtml"
                    filepath = os.path.join(output_dir, "EPUB", filename)
                    
                    with open(filepath, 'w', encoding='utf-8') as f:
                        f.write(xhtml_content)
                    
                    xhtml_files.append({
                        'filename': filename,
                        'filepath': filepath,
                        'title': title,
                        'nav_point': nav_point
                    })
                    
                    print(f"XHTML 파일 생성: {filename} - {title}")
                    current_file_index += 1

    # --- 5. package.opf 생성 ---
    print("package.opf 생성 중...")
    package_opf = create_package_opf(book_title, book_author, book_publisher, book_language, 
                                   book_uid, xhtml_files, daisy_dir)
    
    opf_filepath = os.path.join(output_dir, "EPUB", "package.opf")
    with open(opf_filepath, 'w', encoding='utf-8') as f:
        f.write(package_opf)
    
    # --- 6. nav.xhtml 생성 ---
    print("nav.xhtml 생성 중...")
    nav_xhtml = create_nav_xhtml_from_ncx(book_title, nav_points, xhtml_files, ncx_ns, book_language)
    
    nav_filepath = os.path.join(output_dir, "EPUB", "nav.xhtml")
    with open(nav_filepath, 'w', encoding='utf-8') as f:
        f.write(nav_xhtml)
    
    # --- 7. CSS 파일 생성 ---
    print("CSS 파일 생성 중...")
    css_content = create_css_content()
    
    css_filepath = os.path.join(output_dir, "EPUB", "zedai-css.css")
    with open(css_filepath, 'w', encoding='utf-8') as f:
        f.write(css_content)
    
    # --- 8. zedai-mods.xml 생성 ---
    print("zedai-mods.xml 생성 중...")
    mods_content = create_mods_xml(book_title, book_author, book_language)
    
    mods_filepath = os.path.join(output_dir, "EPUB", "zedai-mods.xml")
    with open(mods_filepath, 'w', encoding='utf-8') as f:
        f.write(mods_content)
    
    print(f"\n--- EPUB3 파일 생성 완료 ---")
    print(f"생성된 파일은 '{output_dir}' 폴더에 있습니다.")
    
    # --- EPUB3 ZIP 파일 생성 ---
    # 안전한 파일명 생성 (특수문자 제거)
    safe_title = re.sub(r'[<>:"/\\|?*]', '_', book_title).strip()
    safe_title = re.sub(r'\s+', '_', safe_title)  # 공백을 언더스코어로 변경
    safe_title = safe_title[:50]  # 파일명 길이 제한
    if not safe_title:
        safe_title = "untitled"
    
    epub_filename = os.path.join(output_dir, f"{safe_title}.epub")
    
    with zipfile.ZipFile(epub_filename, 'w', zipfile.ZIP_DEFLATED, allowZip64=True) as epub_zip:
        # 1. mimetype 파일 (반드시 첫 번째, 압축하지 않음)
        epub_zip.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        
        # 2. META-INF/container.xml (경로 검증 후 추가)
        container_path = os.path.join(output_dir, "META-INF", "container.xml")
        if os.path.exists(container_path):
            epub_zip.write(container_path, "META-INF/container.xml")
        else:
            raise FileNotFoundError(f"container.xml 파일을 찾을 수 없습니다: {container_path}")
        
        # 3. EPUB/package.opf (경로 검증 후 추가)
        package_path = os.path.join(output_dir, "EPUB", "package.opf")
        if os.path.exists(package_path):
            epub_zip.write(package_path, "EPUB/package.opf")
        else:
            raise FileNotFoundError(f"package.opf 파일을 찾을 수 없습니다: {package_path}")
        
        # 4. EPUB/nav.xhtml
        nav_path = os.path.join(output_dir, "EPUB", "nav.xhtml")
        if os.path.exists(nav_path):
            epub_zip.write(nav_path, "EPUB/nav.xhtml")
        else:
            raise FileNotFoundError(f"nav.xhtml 파일을 찾을 수 없습니다: {nav_path}")
        
        # 5. EPUB/zedai-css.css
        css_path = os.path.join(output_dir, "EPUB", "zedai-css.css")
        if os.path.exists(css_path):
            epub_zip.write(css_path, "EPUB/zedai-css.css")
        else:
            raise FileNotFoundError(f"zedai-css.css 파일을 찾을 수 없습니다: {css_path}")
        
        # 6. EPUB/zedai-mods.xml
        mods_path = os.path.join(output_dir, "EPUB", "zedai-mods.xml")
        if os.path.exists(mods_path):
            epub_zip.write(mods_path, "EPUB/zedai-mods.xml")
        else:
            raise FileNotFoundError(f"zedai-mods.xml 파일을 찾을 수 없습니다: {mods_path}")
        
        # 7. EPUB/dtbook-*.xhtml 파일들
        for xhtml_file in xhtml_files:
            if os.path.exists(xhtml_file['filepath']):
                # ZIP 내부 경로는 항상 forward slash 사용
                zip_path = f"EPUB/{xhtml_file['filename']}"
                epub_zip.write(xhtml_file['filepath'], zip_path)
                print(f"XHTML 파일 추가: {zip_path}")
            else:
                raise FileNotFoundError(f"XHTML 파일을 찾을 수 없습니다: {xhtml_file['filepath']}")
        
        # 8. EPUB/ 이미지 파일들 (images 폴더 없이 직접)
        print(f"DAISY 디렉토리에서 이미지 파일 ZIP 추가 확인: {daisy_dir}")
        
        if os.path.exists(daisy_dir):
            all_files = os.listdir(daisy_dir)
            image_files = [f for f in all_files if f.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.svg'))]
            print(f"발견된 이미지 파일들: {image_files}")
            
            for image_file in image_files:
                # EPUB 폴더에 복사된 이미지 파일 경로
                src_path = os.path.join(output_dir, "EPUB", image_file)
                if os.path.exists(src_path):
                    # ZIP 내부 경로는 항상 forward slash 사용 (EPUB 표준)
                    zip_path = f"EPUB/{image_file}"
                    epub_zip.write(src_path, zip_path)
                    print(f"✅ EPUB Core Media Type 이미지 ZIP 추가: {zip_path}")
                else:
                    print(f"❌ 경고: 이미지 파일을 찾을 수 없습니다: {src_path}")
        else:
            print(f"❌ DAISY 디렉토리가 존재하지 않습니다: {daisy_dir}")
    
    print(f"EPUB3 ZIP 파일 생성 완료: {epub_filename}")
    
    # --- ZIP 파일 검증 ---
    print("EPUB 구조 검증 중...")
    try:
        with zipfile.ZipFile(epub_filename, 'r') as verify_zip:
            file_list = verify_zip.namelist()
            print(f"ZIP 파일 내 파일 목록:")
            for file_name in sorted(file_list):
                print(f"  - {file_name}")
            
            # 필수 파일 검증
            required_files = ["mimetype", "META-INF/container.xml", "EPUB/package.opf", "EPUB/nav.xhtml"]
            for req_file in required_files:
                if req_file not in file_list:
                    print(f"경고: 필수 파일이 누락됨 - {req_file}")
                else:
                    print(f"✓ 필수 파일 확인됨 - {req_file}")
    except Exception as e:
        print(f"ZIP 파일 검증 중 오류: {e}")
    
    return epub_filename

def create_title_page_xhtml(book_title, book_author, book_publisher, book_language):
    """Title Page XHTML을 생성합니다."""
    
    title_xhtml = f'''<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="{book_language}" lang="{book_language}">

<head>
  <meta charset="UTF-8" />
  <title>{html.escape(book_title)}</title>
  <link rel="stylesheet" type="text/css" href="zedai-css.css" />
</head>

<body xmlns:epub="http://www.idpf.org/2007/ops" epub:type="frontmatter">
  <section epub:type="titlepage">
    <h1 class="book-title">{html.escape(book_title)}</h1>
    <p class="book-author">{html.escape(book_author)}</p>
    <p class="book-publisher">{html.escape(book_publisher)}</p>
  </section>
</body>

</html>'''
    
    return title_xhtml

def find_element_by_smil_id(bodymatter, smil_id, dtbook_ns):
    """SMIL ID를 기반으로 DTBook 요소를 찾습니다."""
    # smil_id에서 실제 DTBook ID 추출 (예: smil_par_p_160 -> p_160)
    if smil_id.startswith('smil_par_'):
        dtbook_id = smil_id.replace('smil_par_', '')
    else:
        dtbook_id = smil_id
    
    # bodymatter에서 해당 ID를 가진 요소 찾기
    for elem in bodymatter.iter():
        if elem.get('id') == dtbook_id:
            return elem
    
    # ID를 찾을 수 없는 경우, level1 요소들 중에서 찾기
    level1_elements = bodymatter.findall(f"{{{dtbook_ns}}}level1")
    for level1 in level1_elements:
        if level1.get('id') == dtbook_id:
            return level1
    
    return None

def extract_text_content(element, dtbook_ns):
    """DTBook 요소에서 모든 텍스트 내용을 추출합니다."""
    text_parts = []
    
    # 요소 자체의 텍스트
    if element.text:
        text_parts.append(element.text.strip())
    
    # 하위 요소들의 텍스트 재귀적으로 추출
    for child in element:
        if child.tag.endswith('pagenum'):
            # 페이지 번호는 텍스트 추출에서만 건너뛰기 (별도 처리됨)
            continue
        elif child.tag.endswith(('p', 'sent', 'w')):
            # 텍스트 요소들
            if child.text:
                text_parts.append(child.text.strip())
            # 하위 요소도 재귀적으로 처리
            child_text = extract_text_content(child, dtbook_ns)
            if child_text:
                text_parts.append(child_text)
        elif child.tag.endswith('br'):
            # 줄바꿈
            text_parts.append(' ')
        elif child.tag.endswith('imggroup'):
            # imggroup은 텍스트 추출에서 건너뛰기 (별도 이미지 처리됨)
            print(f"🖼️ extract_text_content에서 imggroup 건너뛰기: {child.get('id', 'no-id')}")
            continue
        else:
            # 기타 요소들도 재귀적으로 처리 (pagenum, imggroup 제외)
            child_text = extract_text_content(child, dtbook_ns)
            if child_text:
                text_parts.append(child_text)
        
        # tail 텍스트도 포함
        if child.tail:
            text_parts.append(child.tail.strip())
    
    return ' '.join(filter(None, [part.strip() for part in text_parts]))

def create_xhtml_from_nav_structure(target_element, file_index, title, dtbook_ns, book_title, book_language="ko"):
    """DTBook level 구조를 기반으로 XHTML를 생성합니다."""
    
    # 고유 ID 생성용 카운터
    id_counter = 0
    
    # XHTML 시작
    xhtml = f'''<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="{book_language}" lang="{book_language}">

<head>
  <meta charset="UTF-8" />
  <title>{html.escape(book_title)}</title>
  <link rel="stylesheet" type="text/css" href="zedai-css.css" />
</head>

<body xmlns:epub="http://www.idpf.org/2007/ops" epub:type="bodymatter">'''
    
    # level1 섹션 시작 (파일별 고유 ID)
    section_id = target_element.get('id', f'section_f{file_index}_p1')
    main_heading_id = f"heading_f{file_index}_{id_counter}"
    id_counter += 1
    
    # 원본 DAISY에서 헤딩 레벨 찾기
    heading_tag = "h1"  # 기본값
    for child in target_element:
        if child.tag.endswith(('h1', 'h2', 'h3', 'h4', 'h5', 'h6')):
            heading_tag = child.tag.split('}')[-1] if '}' in child.tag else child.tag
            break
    
    xhtml += f'''
  <section id="{section_id}">
    <{heading_tag} id="{main_heading_id}">{html.escape(title)}</{heading_tag}>'''
    
    # target_element의 내용을 계층적으로 처리 (NCX가 아닌 실제 DTBook 구조 사용)
    xhtml += process_dtbook_level_content(target_element, dtbook_ns, file_index, 1, skip_main_heading=True)
    
    # level1 섹션 종료
    xhtml += '''
  </section>
</body>

</html>'''
    
    return xhtml

def process_dtbook_level_content(element, dtbook_ns, file_index=0, level=1, skip_main_heading=True):
    """DTBook level 요소를 계층적으로 처리하여 XHTML로 변환합니다."""
    content = ""
    element_counter = 0
    
    for child in element:
        print(f"🔍 처리 중인 요소: {child.tag}, id: {child.get('id', 'no-id')}")
        
        # imggroup 특별 체크
        if 'imggroup' in child.tag:
            print(f"🚨 IMGGROUP 태그 발견됨! 전체 태그: {child.tag}")
        
        if child.tag.endswith('imggroup'):
            # 이미지 그룹 처리 - 최우선으로 처리
            print(f"🖼️ IMGGROUP 발견! id: {child.get('id', 'no-id')}")
            print(f"    imggroup 내부 요소들: {[elem.tag for elem in child]}")
            
            # 더 강화된 img 요소 찾기
            img_elem = None
            
            # 1. 네임스페이스 포함해서 img 요소 찾기
            img_elem = child.find(f"{{{dtbook_ns}}}img")
            print(f"    네임스페이스 포함 img 요소 찾기 결과: {img_elem is not None}")
            
            # 2. 네임스페이스 없이도 시도해보기
            if img_elem is None:
                img_elem = child.find("img")
                print(f"    네임스페이스 없이 img 요소 찾기 결과: {img_elem is not None}")
            
            # 3. 모든 하위 요소 중에서 tag가 img로 끝나는 것 찾기
            if img_elem is None:
                for elem in child:
                    print(f"      검사 중인 하위 요소: {elem.tag}")
                    if elem.tag.endswith('img'):
                        img_elem = elem
                        print(f"    tag 끝검사로 img 요소 발견: {elem.tag}")
                        break
            
            # 4. XPath로도 시도해보기
            if img_elem is None:
                try:
                    img_elems = child.xpath('.//img')
                    if img_elems:
                        img_elem = img_elems[0]
                        print(f"    XPath로 img 요소 발견: {img_elem.tag}")
                except Exception as e:
                    print(f"    XPath 검색 실패: {e}")
            
            # 5. 네임스페이스를 직접 확인해서 찾기
            if img_elem is None:
                for elem in child:
                    if 'img' in elem.tag:
                        img_elem = elem
                        print(f"    네임스페이스 직접 확인으로 img 요소 발견: {elem.tag}")
                        break
            
            print(f"    최종 img 요소 발견 여부: {img_elem is not None}")
            
            if img_elem is not None:
                img_src = img_elem.get('src', '')
                img_alt = img_elem.get('alt', '')
                img_id = img_elem.get('id', f'img_f{file_index}_{element_counter}')
                element_counter += 1
                
                # 이미지 파일명 추출
                img_filename = os.path.basename(img_src)
                print(f"🖼️ 이미지 처리 (process_dtbook_level_content): src='{img_src}' -> filename='{img_filename}'")
                
                # 캡션 요소 찾기
                caption_elem = child.find(f"{{{dtbook_ns}}}caption")
                caption_text = img_alt  # 기본값
                
                if caption_elem is not None:
                    # 캡션 내부의 모든 텍스트 추출
                    caption_parts = []
                    if caption_elem.text:
                        caption_parts.append(caption_elem.text.strip())
                    
                    for sent in caption_elem.findall(f"{{{dtbook_ns}}}sent"):
                        if sent.text:
                            caption_parts.append(sent.text.strip())
                        for w in sent.findall(f"{{{dtbook_ns}}}w"):
                            if w.text:
                                caption_parts.append(w.text.strip())
                    
                    if caption_parts:
                        caption_text = " ".join(caption_parts)
                
                print(f"    📝 EPUB 3.0 표준 이미지 생성: <img src=\"{img_filename}\" alt=\"{img_alt}\" />")
                
                # EPUB 3.0 표준 figure 구조
                content += f'''
      <figure id="{img_id}">
        <img src="{img_filename}" alt="{html.escape(img_alt)}" />'''
                
                # 캡션이 있는 경우에만 figcaption 추가
                if caption_text and caption_text.strip() and caption_text != img_alt:
                    content += f'''
        <figcaption id="caption_f{file_index}_{element_counter}">
          {html.escape(caption_text)}
        </figcaption>'''
                
                content += '''
      </figure>'''
            else:
                # img 요소를 찾지 못한 경우에도 빈 p 태그를 만들지 않음
                print(f"    ❌ img 요소를 찾지 못했습니다. imggroup 건너뛰기: id={child.get('id', 'no-id')}")
                # imggroup이 제대로 처리되지 않았지만 빈 태그로 변환하지 않음
                
        elif child.tag.endswith(('h1', 'h2', 'h3', 'h4', 'h5', 'h6')) and skip_main_heading:
            # 메인 헤딩은 이미 처리했으므로 건너뛰기
            continue
        elif child.tag.endswith('pagenum'):
            # DAISY Pipeline 방식의 페이지 번호 처리
            page_num = child.text.strip() if child.text else ""
            page_id = child.get('id', f'pagebreak_f{file_index}_{element_counter}')
            element_counter += 1
            
            # DAISY Pipeline과 동일한 형식
            content += f'''<span aria-label=" {page_num}. " role="doc-pagebreak" epub:type="pagebreak" id="{page_id}"></span>'''
            
        elif child.tag.endswith('p'):
            # imggroup이 잘못 p로 처리되지 않도록 확인
            if 'imggroup' in child.tag:
                print(f"⚠️ imggroup이 p 태그로 잘못 처리되려 했습니다: {child.tag}, id: {child.get('id', 'no-id')}")
                # imggroup을 p 태그로 처리하지 않고 건너뛰기
                continue
                
            # 단락 처리
            p_id = child.get('id', f'para_f{file_index}_{element_counter}')
            p_text = extract_text_content(child, dtbook_ns)
            element_counter += 1
            
            # 일반 단락
            content += f'''
      <p id="{p_id}">{html.escape(p_text)}</p>'''
            
        elif child.tag.endswith(('level2', 'level3', 'level4', 'level5', 'level6')):
            # 하위 레벨 처리
            level_num = int(child.tag[-1]) if child.tag[-1].isdigit() else level + 1
            level_id = child.get('id', f'level{level_num}_f{file_index}_{element_counter}')
            element_counter += 1
            
            # 헤딩 찾기
            heading_elem = None
            heading_text = f"Section {level_num}"
            heading_tag = f"h{level_num}"
            
            for subchild in child:
                if subchild.tag.endswith(('h1', 'h2', 'h3', 'h4', 'h5', 'h6')):
                    heading_elem = subchild
                    heading_text = subchild.text if subchild.text else f"Section {level_num}"
                    heading_tag = subchild.tag.split('}')[-1] if '}' in subchild.tag else subchild.tag
                    break
            
            # 하위 레벨 섹션 시작
            content += f'''
    <section id="{level_id}">
      <{heading_tag} id="heading_f{file_index}_{element_counter}">{html.escape(heading_text)}</{heading_tag}>'''
            element_counter += 1
            
            # 하위 레벨 내용 재귀 처리 (하위 레벨에서는 헤딩을 포함)
            subcontent = process_dtbook_level_content(child, dtbook_ns, file_index, level_num, skip_main_heading=False)
            content += subcontent
            
            # 하위 레벨 섹션 종료
            content += '''
    </section>'''
                
        elif child.tag.endswith('table'):
            # DAISY Pipeline 방식의 표 처리
            table_id = child.get('id', f'table_f{file_index}_{element_counter}')
            element_counter += 1
            
            content += f'''
      <table id="{table_id}">'''
            
            # 표 캡션 처리
            caption_elem = child.find(f"{{{dtbook_ns}}}caption")
            if caption_elem is not None:
                caption_text = extract_text_content(caption_elem, dtbook_ns)
                if caption_text:
                    content += f'''
        <caption>{html.escape(caption_text)}</caption>'''
            
            # tbody 처리 (DAISY Pipeline은 항상 tbody 사용)
            tbody = child.find(f"{{{dtbook_ns}}}tbody")
            if tbody is not None:
                tbody_id = tbody.get('id', f'tbody_f{file_index}_{element_counter}')
                content += f'''
        <tbody id="{tbody_id}">'''
                
                cell_id_counter = 1
                for row_idx, tr in enumerate(tbody.findall(f"{{{dtbook_ns}}}tr")):
                    tr_id = tr.get('id', f'tr_f{file_index}_{row_idx}')
                    content += f'''
          <tr id="{tr_id}">'''
                    
                    # DAISY Pipeline 방식: th와 td를 순서대로 처리
                    for cell_idx, cell in enumerate(tr):
                        if cell.tag.endswith(('th', 'td')):
                            cell_id = cell.get('id', f'id_{cell_id_counter}')
                            cell_id_counter += 1
                            
                            # 셀 내용 추출 (DAISY Pipeline은 셀 내부에 p 태그 사용)
                            cell_content = ""
                            for p in cell.findall(f"{{{dtbook_ns}}}p"):
                                p_id = p.get('id', f'table_{table_id}_cell_{row_idx}_{cell_idx}')
                                p_text = extract_text_content(p, dtbook_ns)
                                cell_content += f'''
                <p id="{p_id}">{html.escape(p_text)}</p>'''
                            
                            # 셀 내용이 없으면 직접 텍스트 사용
                            if not cell_content:
                                cell_text = extract_text_content(cell, dtbook_ns)
                                if cell_text:
                                    p_id = f'table_{table_id}_cell_{row_idx}_{cell_idx}'
                                    cell_content = f'''
                <p id="{p_id}">{html.escape(cell_text)}</p>'''
                            
                            # 셀 병합 속성 처리
                            attrs = ''
                            if cell.get('rowspan'):
                                attrs += f' rowspan="{cell.get("rowspan")}"'
                            if cell.get('colspan'):
                                attrs += f' colspan="{cell.get("colspan")}"'
                            
                            # th 또는 td 생성 (DAISY Pipeline 방식)
                            if cell.tag.endswith('th'):
                                # th에는 scope 속성 추가
                                scope = 'row' if cell_idx == 0 else 'col'
                                content += f'''
            <th id="{cell_id}" scope="{scope}"{attrs}>{cell_content}
            </th>'''
                            else:
                                content += f'''
            <td id="{cell_id}"{attrs}>{cell_content}
            </td>'''
                    
                    content += '''
          </tr>'''
                
                content += '''
        </tbody>'''
            
            content += '''
      </table>'''
        else:
            # 처리되지 않은 요소 로깅 및 빈 p 태그 방지
            if child.tag.endswith('imggroup'):
                # imggroup이 여기까지 왔다면 이미 위에서 처리되었거나 처리 실패
                print(f"⚠️ IMGGROUP 재처리 방지: {child.tag}, id: {child.get('id', 'no-id')}")
            else:
                print(f"⚠️ 처리되지 않은 요소: {child.tag}, id: {child.get('id', 'no-id')}")
                # 알 수 없는 요소를 빈 p 태그로 변환하는 로직 방지
                # 원본 id를 유지한 빈 p 태그가 생성되지 않도록 함
    
    return content

def create_xhtml_from_level1(level1, file_index, dtbook_ns, book_title, book_language="ko"):
    """level1 요소를 XHTML로 변환합니다."""
    
    # level1에서 헤딩 요소 찾기 (h1, h2, h3 등)
    heading_elem = None
    heading_tag = "h1"  # 기본값
    title = f"Section {file_index}"
    
    for child in level1:
        if child.tag.endswith(('h1', 'h2', 'h3', 'h4', 'h5', 'h6')):
            heading_elem = child
            heading_tag = child.tag.split('}')[-1] if '}' in child.tag else child.tag
            title = child.text if child.text else f"Section {file_index}"
            break
    
    # XHTML 시작
    xhtml = f'''<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="{book_language}" lang="{book_language}">

<head>
  <meta charset="UTF-8" />
  <title>{html.escape(book_title)}</title>
  <link rel="stylesheet" type="text/css" href="zedai-css.css" />
</head>

<body xmlns:epub="http://www.idpf.org/2007/ops" epub:type="bodymatter">
  <section id="section_f{file_index}_level1">
    <{heading_tag} id="heading_f{file_index}_main">{html.escape(title)}</{heading_tag}>'''
    
    # level1 내부의 모든 요소들을 순회
    element_counter = 0
    
    for elem in level1:
        print(f"🔍 level1에서 처리 중인 요소: {elem.tag}, id: {elem.get('id', 'no-id')}")
        
        # imggroup 특별 체크 (level1 버전)
        if 'imggroup' in elem.tag:
            print(f"🚨 LEVEL1에서 IMGGROUP 태그 발견됨! 전체 태그: {elem.tag}")
        
        if elem.tag.endswith('imggroup'):
            # 이미지 그룹 처리 - 최우선으로 처리
            print(f"🖼️ level1에서 IMGGROUP 발견! id: {elem.get('id', 'no-id')}")
            print(f"    level1 imggroup 내부 요소들: {[e.tag for e in elem]}")
            
            # 더 강화된 img 요소 찾기
            img_elem = None
            
            # 1. 네임스페이스 포함해서 img 요소 찾기
            img_elem = elem.find(f"{{{dtbook_ns}}}img")
            print(f"    level1 네임스페이스 포함 img 요소 찾기 결과: {img_elem is not None}")
            
            # 2. 네임스페이스 없이도 시도해보기
            if img_elem is None:
                img_elem = elem.find("img")
                print(f"    level1 네임스페이스 없이 img 요소 찾기 결과: {img_elem is not None}")
            
            # 3. 모든 하위 요소 중에서 tag가 img로 끝나는 것 찾기
            if img_elem is None:
                for e in elem:
                    print(f"      level1 검사 중인 하위 요소: {e.tag}")
                    if e.tag.endswith('img'):
                        img_elem = e
                        print(f"    level1 tag 끝검사로 img 요소 발견: {e.tag}")
                        break
            
            # 4. XPath로도 시도해보기
            if img_elem is None:
                try:
                    img_elems = elem.xpath('.//img')
                    if img_elems:
                        img_elem = img_elems[0]
                        print(f"    level1 XPath로 img 요소 발견: {img_elem.tag}")
                except Exception as e:
                    print(f"    level1 XPath 검색 실패: {e}")
            
            # 5. 네임스페이스를 직접 확인해서 찾기
            if img_elem is None:
                for e in elem:
                    if 'img' in e.tag:
                        img_elem = e
                        print(f"    level1 네임스페이스 직접 확인으로 img 요소 발견: {e.tag}")
                        break
            
            print(f"    level1 최종 img 요소 발견 여부: {img_elem is not None}")
            
            if img_elem is not None:
                img_src = img_elem.get('src', '')
                img_alt = img_elem.get('alt', '')
                img_id = img_elem.get('id', f'img_f{file_index}_{element_counter}')
                element_counter += 1
                
                # 이미지 파일명 추출
                img_filename = os.path.basename(img_src)
                print(f"🖼️ 이미지 처리 (create_xhtml_from_level1): src='{img_src}' -> filename='{img_filename}'")
                
                # 캡션 요소 찾기
                caption_elem = elem.find(f"{{{dtbook_ns}}}caption")
                caption_text = img_alt  # 기본값
                
                if caption_elem is not None:
                    # 캡션 내부의 모든 텍스트 추출
                    caption_parts = []
                    if caption_elem.text:
                        caption_parts.append(caption_elem.text.strip())
                    
                    for sent in caption_elem.findall(f"{{{dtbook_ns}}}sent"):
                        if sent.text:
                            caption_parts.append(sent.text.strip())
                        for w in sent.findall(f"{{{dtbook_ns}}}w"):
                            if w.text:
                                caption_parts.append(w.text.strip())
                    
                    if caption_parts:
                        caption_text = " ".join(caption_parts)
                
                print(f"    📝 level1 EPUB 3.0 표준 이미지 생성: <img src=\"{img_filename}\" alt=\"{img_alt}\" />")
                
                # EPUB 3.0 표준 figure 구조
                xhtml += f'''
    <figure id="{img_id}">
      <img src="{img_filename}" alt="{html.escape(img_alt)}" />'''
                
                # 캡션이 있는 경우에만 figcaption 추가
                if caption_text and caption_text.strip() and caption_text != img_alt:
                    xhtml += f'''
      <figcaption id="caption_f{file_index}_{element_counter}">
        {html.escape(caption_text)}
      </figcaption>'''
                
                xhtml += '''
    </figure>'''
            else:
                # img 요소를 찾지 못한 경우에도 빈 p 태그를 만들지 않음
                print(f"    ❌ level1 img 요소를 찾지 못했습니다. imggroup 건너뛰기: id={elem.get('id', 'no-id')}")
                # imggroup이 제대로 처리되지 않았지만 빈 태그로 변환하지 않음
                
        elif elem.tag.endswith(('h1', 'h2', 'h3', 'h4', 'h5', 'h6')):
            # 헤딩은 이미 처리했으므로 건너뛰기
            continue
        elif elem.tag.endswith('pagenum'):
            # DAISY Pipeline 방식의 페이지 번호 처리
            page_num = elem.text.strip() if elem.text else ""
            page_id = elem.get('id', f'pagebreak_f{file_index}_{element_counter}')
            element_counter += 1
            
            # DAISY Pipeline과 동일한 형식
            xhtml += f'''<span aria-label=" {page_num}. " role="doc-pagebreak" epub:type="pagebreak" id="{page_id}"></span>'''
        elif elem.tag.endswith('p'):
            # imggroup이 잘못 p로 처리되지 않도록 확인
            if 'imggroup' in elem.tag:
                print(f"⚠️ level1에서 imggroup이 p 태그로 잘못 처리되려 했습니다: {elem.tag}, id: {elem.get('id', 'no-id')}")
                # imggroup을 p 태그로 처리하지 않고 건너뛰기
                continue
                
            # 단락 처리
            p_id = elem.get('id', f'para_f{file_index}_{element_counter}')
            p_text = extract_text_content(elem, dtbook_ns)
            element_counter += 1
            
            # 일반 단락
            xhtml += f'''
    <p id="{p_id}">{html.escape(p_text)}</p>'''
                
        elif elem.tag.endswith('table'):
            # DAISY Pipeline 방식의 표 처리
            table_id = elem.get('id', f'table_f{file_index}_{element_counter}')
            element_counter += 1
            
            xhtml += f'''
    <table id="{table_id}">'''
            
            # 표 캡션 처리
            caption_elem = elem.find(f"{{{dtbook_ns}}}caption")
            if caption_elem is not None:
                caption_text = extract_text_content(caption_elem, dtbook_ns)
                if caption_text:
                    xhtml += f'''
      <caption>{html.escape(caption_text)}</caption>'''
            
            # tbody 처리 (DAISY Pipeline은 항상 tbody 사용)
            tbody = elem.find(f"{{{dtbook_ns}}}tbody")
            if tbody is not None:
                tbody_id = tbody.get('id', f'tbody_f{file_index}_{element_counter}')
                xhtml += f'''
      <tbody id="{tbody_id}">'''
                
                cell_id_counter = 1
                for row_idx, tr in enumerate(tbody.findall(f"{{{dtbook_ns}}}tr")):
                    tr_id = tr.get('id', f'tr_f{file_index}_{row_idx}')
                    xhtml += f'''
        <tr id="{tr_id}">'''
                    
                    # DAISY Pipeline 방식: th와 td를 순서대로 처리
                    for cell_idx, cell in enumerate(tr):
                        if cell.tag.endswith(('th', 'td')):
                            cell_id = cell.get('id', f'id_{cell_id_counter}')
                            cell_id_counter += 1
                            
                            # 셀 내용 추출 (DAISY Pipeline은 셀 내부에 p 태그 사용)
                            cell_content = ""
                            for p in cell.findall(f"{{{dtbook_ns}}}p"):
                                p_id = p.get('id', f'table_{table_id}_cell_{row_idx}_{cell_idx}')
                                p_text = extract_text_content(p, dtbook_ns)
                                cell_content += f'''
          <p id="{p_id}">{html.escape(p_text)}</p>'''
                            
                            # 셀 내용이 없으면 직접 텍스트 사용
                            if not cell_content:
                                cell_text = extract_text_content(cell, dtbook_ns)
                                if cell_text:
                                    p_id = f'table_{table_id}_cell_{row_idx}_{cell_idx}'
                                    cell_content = f'''
          <p id="{p_id}">{html.escape(cell_text)}</p>'''
                            
                            # 셀 병합 속성 처리
                            attrs = ''
                            if cell.get('rowspan'):
                                attrs += f' rowspan="{cell.get("rowspan")}"'
                            if cell.get('colspan'):
                                attrs += f' colspan="{cell.get("colspan")}"'
                            
                            # th 또는 td 생성 (DAISY Pipeline 방식)
                            if cell.tag.endswith('th'):
                                # th에는 scope 속성 추가
                                scope = 'row' if cell_idx == 0 else 'col'
                                xhtml += f'''
          <th id="{cell_id}" scope="{scope}"{attrs}>{cell_content}
          </th>'''
                            else:
                                xhtml += f'''
          <td id="{cell_id}"{attrs}>{cell_content}
          </td>'''
                    
                    xhtml += '''
        </tr>'''
                
                xhtml += '''
      </tbody>'''
            
            xhtml += '''
    </table>'''
        else:
            # 처리되지 않은 요소 로깅 및 빈 p 태그 방지
            if elem.tag.endswith('imggroup'):
                # imggroup이 여기까지 왔다면 이미 위에서 처리되었거나 처리 실패
                print(f"⚠️ level1 IMGGROUP 재처리 방지: {elem.tag}, id: {elem.get('id', 'no-id')}")
            else:
                print(f"⚠️ level1에서 처리되지 않은 요소: {elem.tag}, id: {elem.get('id', 'no-id')}")
                # 알 수 없는 요소를 빈 p 태그로 변환하는 로직 방지
                # 원본 id를 유지한 빈 p 태그가 생성되지 않도록 함
    
    # XHTML 종료
    xhtml += '''
  </section>
</body>

</html>'''
    
    return xhtml

def create_package_opf(book_title, book_author, book_publisher, book_language, book_uid, xhtml_files, daisy_dir):
    """package.opf 파일 내용을 생성합니다."""
    
    # 고유 식별자 생성 (book_uid를 안전한 ID로 변환)
    unique_id = "uid_" + re.sub(r'[^a-zA-Z0-9_-]', '_', str(book_uid))
    
    opf = f'''<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf"
         xml:lang="{book_language}"
         prefix="dcterms: http://purl.org/dc/terms/ schema: http://schema.org/"
         unique-identifier="{unique_id}"
         version="3.0">
    <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
        <dc:title>
            {html.escape(book_title)}
        </dc:title>
        <dc:identifier id="{unique_id}">
            {book_uid}
        </dc:identifier>
        <dc:language>
            {book_language}
        </dc:language>
        <dc:creator>
            {html.escape(book_author)}
        </dc:creator>
        <dc:publisher>
            {html.escape(book_publisher)}
        </dc:publisher>
        <meta property="dcterms:modified">
            {datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")}
        </meta>
        <meta property="schema:accessibilityFeature">
            tableOfContents
        </meta>
        <meta property="schema:accessMode">
            textual
        </meta>
        <meta property="schema:accessibilityHazard">
            unknown
        </meta>
    </metadata>
    <manifest>'''
    
    # XHTML 파일들 추가
    for i, xhtml_file in enumerate(xhtml_files, 1):
        opf += f'''
        <item href="{xhtml_file['filename']}"
              media-type="application/xhtml+xml"
              id="item_{i}" />'''
    
    # nav.xhtml 추가
    opf += f'''
        <item href="nav.xhtml"
              media-type="application/xhtml+xml"
              id="nav"
              properties="nav" />'''
    
    # CSS 파일 추가
    opf += f'''
        <item href="zedai-css.css"
              media-type="text/css"
              id="css" />'''
    
    # MODS 파일 추가
    opf += f'''
        <item href="zedai-mods.xml"
              media-type="application/mods+xml"
              id="mods" />'''
    
    # 이미지 파일들 추가 (EPUB 3.0 Core Media Types만 지원)
    if os.path.exists(daisy_dir):
        all_files = os.listdir(daisy_dir)
        image_files = [f for f in all_files if f.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.svg'))]
        
        image_counter = len(xhtml_files) + 4  # XHTML + nav + css + mods
        for image_file in image_files:
            # EPUB 3.0 Core Media Types만 지원
            if image_file.lower().endswith(('.jpg', '.jpeg')):
                mime_type = "image/jpeg"
            elif image_file.lower().endswith('.png'):
                mime_type = "image/png"  
            elif image_file.lower().endswith('.gif'):
                mime_type = "image/gif"
            elif image_file.lower().endswith('.svg'):
                mime_type = "image/svg+xml"
            else:
                print(f"⚠️ EPUB Core Media Type이 아닌 이미지 형식 건너뛰기: {image_file}")
                continue
                
            print(f"✅ EPUB Core Media Type 이미지 매니페스트 추가: {image_file} (MIME: {mime_type})")
            
            # EPUB 3.0 표준 manifest 항목 생성
            opf += f'''
        <item href="{image_file}"
              media-type="{mime_type}"
              id="img_{image_counter}" />'''
            image_counter += 1
    
    opf += '''
    </manifest>
    <spine>'''
    
    # spine에 XHTML 파일들 추가 (nav.xhtml은 spine에 포함하지 않음)
    for i, xhtml_file in enumerate(xhtml_files, 1):
        opf += f'''
        <itemref idref="item_{i}" />'''
    
    opf += '''
    </spine>
</package>'''
    
    return opf

def create_nav_xhtml_from_ncx(book_title, nav_points, xhtml_files, ncx_ns, book_language="ko"):
    """NCX 구조를 기반으로 nav.xhtml 파일 내용을 생성합니다."""
    
    nav = f'''<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="{book_language}" lang="{book_language}">
<head>
    <meta charset="UTF-8" />
    <title>{html.escape(book_title)}</title>
    <link rel="stylesheet" type="text/css" href="zedai-css.css" />
</head>
<body xmlns:epub="http://www.idpf.org/2007/ops">
    <nav epub:type="toc">
        <h1>Table of Contents</h1>
        <ol>'''
    
    # xhtml_files와 nav_points를 매칭
    xhtml_file_map = {i+1: xhtml_file for i, xhtml_file in enumerate(xhtml_files)}
    
    # Title page를 첫 번째 항목으로 추가
    if xhtml_files:
        title_file = xhtml_files[0]
        nav += f'''
                        <li id="title_page" class="level1"><a href="{title_file['filename']}">{html.escape(title_file['title'])}</a></li>'''
    
    # 각 level1 navPoint에 대한 목차 항목 생성
    for i, nav_point in enumerate(nav_points):
        if nav_point.get('class') == 'level1':
            nav_label = nav_point.find(f"{{{ncx_ns}}}navLabel")
            title = nav_label.find(f"{{{ncx_ns}}}text").text if nav_label is not None and nav_label.find(f"{{{ncx_ns}}}text") is not None else f"Section {i+1}"
            
            # 해당하는 XHTML 파일 찾기 (title page 이후부터)
            xhtml_file = xhtml_file_map.get(i+2, {'filename': f'dtbook-{i+2}.xhtml'})
            
            nav += f'''
                        <li id="{nav_point.get('id', '')}" class="level1"><a href="{xhtml_file['filename']}#{nav_point.get('id', '').replace('ncx_', '')}">{html.escape(title)}</a>'''
            
            # level2 navPoint들 찾기
            level2_nav_points = nav_point.findall(f"{{{ncx_ns}}}navPoint")
            if level2_nav_points:
                nav += '''
                                <ol>'''
                for level2_nav in level2_nav_points:
                    if level2_nav.get('class') == 'level2':
                        level2_label = level2_nav.find(f"{{{ncx_ns}}}navLabel")
                        if level2_label is not None:
                            level2_title = level2_label.find(f"{{{ncx_ns}}}text").text if level2_label.find(f"{{{ncx_ns}}}text") is not None else ""
                            nav += f'''
                                        <li id="{level2_nav.get('id', '')}" class="level2"><a href="{xhtml_file['filename']}#{level2_nav.get('id', '').replace('ncx_', '')}">{html.escape(level2_title)}</a></li>'''
                nav += '''
                                </ol>'''
            
            nav += '''
                        </li>'''
    
    nav += '''
        </ol>
    </nav>
</body>
</html>'''
    
    return nav

def create_css_content():
    """CSS 파일 내용을 생성합니다."""
    return '''/* EPUB3 CSS for DAISY conversion */

body {
    font-family: "Malgun Gothic", "맑은 고딕", sans-serif;
    line-height: 1.6;
    margin: 0;
    padding: 20px;
    background-color: #ffffff;
    color: #000000;
}

/* Title page styles */
[epub\\:type="titlepage"] {
    text-align: center;
    padding: 40px 20px;
    min-height: 60vh;
    display: flex;
    flex-direction: column;
    justify-content: center;
    align-items: center;
}

.book-title {
    font-size: 2.5em;
    font-weight: bold;
    margin-bottom: 1em;
    color: #2c3e50;
    line-height: 1.2;
}

.book-author {
    font-size: 1.5em;
    margin-bottom: 0.5em;
    color: #34495e;
    font-style: italic;
}

.book-publisher {
    font-size: 1.2em;
    color: #7f8c8d;
    margin-top: 1em;
}

h1, h2, h3, h4, h5, h6 {
    font-weight: bold;
    margin-top: 1em;
    margin-bottom: 0.5em;
}

h1 {
    font-size: 1.8em;
    color: #2c3e50;
}

h2 {
    font-size: 1.5em;
    color: #34495e;
}

h3 {
    font-size: 1.3em;
    color: #34495e;
}

p {
    margin: 0.5em 0;
    text-align: justify;
}

/* EPUB 3.0 표준 이미지 스타일 */
figure {
    margin: 1em 0;
    text-align: center;
    clear: both;
}

figure img {
    max-width: 100%;
    height: auto;
    display: block;
    margin: 0 auto;
}

figcaption {
    font-style: italic;
    margin-top: 0.5em;
    font-size: 0.9em;
    color: #666;
    text-align: center;
    padding: 0.5em;
}

table {
    border-collapse: collapse;
    width: 100%;
    margin: 1em 0;
}

th, td {
    border: 1px solid #ddd;
    padding: 8px;
    text-align: left;
}

th {
    background-color: #f2f2f2;
    font-weight: bold;
}

/* DAISY Pipeline 방식 페이지 브레이크 스타일 */
[epub\\:type="pagebreak"] {
    display: none;
    page-break-before: always;
}

[role="doc-pagebreak"] {
    display: none;
    page-break-before: always;
}

/* Navigation styling */
nav {
    margin: 1em 0;
}

nav ol {
    list-style-type: decimal;
    padding-left: 2em;
}

nav li {
    margin: 0.3em 0;
}

nav a {
    text-decoration: none;
    color: #2980b9;
}

nav a:hover {
    text-decoration: underline;
}

.level1 {
    font-weight: bold;
}

.level2 {
    font-weight: normal;
    margin-left: 1em;
}

/* Accessibility features */

/* Print styles */
@media print {
    body {
        font-size: 12pt;
        line-height: 1.4;
    }
    
    h1, h2, h3 {
        page-break-after: avoid;
    }
    
    p {
        orphans: 3;
        widows: 3;
    }
}'''

def create_mods_xml(book_title, book_author, book_language):
    """zedai-mods.xml 파일 내용을 생성합니다."""
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<mods xmlns="http://www.loc.gov/mods/v3" xmlns:xlink="http://www.w3.org/1999/xlink" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="http://www.loc.gov/mods/v3 http://www.loc.gov/standards/mods/v3/mods-3-7.xsd">
    <titleInfo>
        <title>{html.escape(book_title)}</title>
    </titleInfo>
    <name type="personal">
        <namePart>{html.escape(book_author)}</namePart>
        <role>
            <roleTerm type="text">author</roleTerm>
        </role>
    </name>
    <language>
        <languageTerm type="code" authority="iso639-2b">{book_language}</languageTerm>
    </language>
    <physicalDescription>
        <form authority="marcform">electronic</form>
        <internetMediaType>application/epub+zip</internetMediaType>
    </physicalDescription>
    <typeOfResource>text</typeOfResource>
</mods>'''

def zip_epub_output(source_dir, output_zip_filename):
    """지정된 폴더의 내용을 EPUB ZIP 파일로 압축합니다."""
    
    if not os.path.isdir(source_dir):
        print(f"오류: 소스 디렉토리를 찾을 수 없습니다 - {source_dir}")
        return

    try:
        print(f"'{source_dir}' 폴더를 '{output_zip_filename}' EPUB 파일로 압축 중...")
        
        with zipfile.ZipFile(output_zip_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
            # mimetype 파일을 먼저 추가 (압축하지 않음)
            mimetype_path = os.path.join(source_dir, "mimetype")
            if os.path.exists(mimetype_path):
                zipf.write(mimetype_path, arcname="mimetype", compress_type=zipfile.ZIP_STORED)
                print("  추가 중: mimetype (압축 없음)")
            
            # 나머지 파일들을 압축하여 추가
            for root, dirs, files in os.walk(source_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    archive_name = os.path.relpath(file_path, source_dir)
                    
                    # mimetype은 이미 추가했으므로 건너뛰기
                    if archive_name == "mimetype":
                        continue
                    
                    print(f"  추가 중: {archive_name}")
                    zipf.write(file_path, arcname=archive_name)
        
        print(f"EPUB 파일 생성 완료: {output_zip_filename}")
    except Exception as e:
        print(f"EPUB 파일 생성 중 오류 발생: {e}")

def main():
    """메인 함수 - 명령행 인터페이스"""
    parser = argparse.ArgumentParser(description="DAISY3에서 EPUB3로 변환")
    parser.add_argument("daisy_dir", help="DAISY 파일들이 있는 디렉토리 경로")
    parser.add_argument("output_dir", help="출력 디렉토리 경로")
    parser.add_argument("--title", help="책 제목")
    parser.add_argument("--author", help="저자")
    parser.add_argument("--publisher", help="출판사")
    parser.add_argument("--language", default="ko", help="언어 코드 (기본값: ko)")
    parser.add_argument("--zip", action="store_true", help="EPUB ZIP 파일로 압축")
    
    args = parser.parse_args()
    
    try:
        # EPUB3 파일 생성
        epub_dir = create_epub3_from_daisy(
            args.daisy_dir, 
            args.output_dir,
            args.title,
            args.author,
            args.publisher,
            args.language
        )
        
        # ZIP 압축 옵션이 있으면 EPUB 파일 생성
        if args.zip:
            epub_filename = os.path.join(args.output_dir, "result.epub")
            zip_epub_output(epub_dir, epub_filename)
            
    except Exception as e:
        print(f"오류: {e}")
        return 1
    
    return 0

if __name__ == "__main__":
    exit(main())
