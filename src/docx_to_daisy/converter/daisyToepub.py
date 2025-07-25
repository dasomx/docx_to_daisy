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
    """DAISY 파일들을 EPUB3 형식으로 변환합니다.

    Args:
        daisy_dir (str): DAISY 파일들이 있는 디렉토리 경로
        output_dir (str): 생성된 EPUB3 파일 저장 폴더
        book_title (str, optional): 책 제목. 기본값은 None (DAISY에서 추출)
        book_author (str, optional): 저자. 기본값은 None (DAISY에서 추출)
        book_publisher (str, optional): 출판사. 기본값은 None (DAISY에서 추출)
        book_language (str, optional): 언어 코드 (ISO 639-1). 기본값은 "ko"
    """
    
    # --- 출력 디렉토리 생성 ---
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(os.path.join(output_dir, "EPUB"), exist_ok=True)
    os.makedirs(os.path.join(output_dir, "META-INF"), exist_ok=True)
    os.makedirs(os.path.join(output_dir, "EPUB", "images"), exist_ok=True)

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
    container_root = etree.Element("container", 
                                  xmlns="urn:oasis:names:tc:opendocument:xmlns:container",
                                  version="1.0")
    rootfiles = etree.SubElement(container_root, "rootfiles")
    rootfile = etree.SubElement(rootfiles, "rootfile",
                               full_path="EPUB/package.opf",
                               media_type="application/oebps-package+xml")
    
    container_file = os.path.join(output_dir, "META-INF", "container.xml")
    container_tree = etree.ElementTree(container_root)
    with open(container_file, 'wb') as f:
        f.write('<?xml version="1.0" encoding="utf-8"?>\n'.encode('utf-8'))
        container_tree.write(f, encoding='utf-8', pretty_print=True, xml_declaration=False)

    # --- 3. 이미지 파일 복사 ---
    print("이미지 파일 복사 중...")
    daisy_images_dir = os.path.join(daisy_dir, "images")
    epub_images_dir = os.path.join(output_dir, "EPUB", "images")
    
    if os.path.exists(daisy_images_dir):
        for image_file in os.listdir(daisy_images_dir):
            if image_file.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.bmp')):
                src_path = os.path.join(daisy_images_dir, image_file)
                dst_path = os.path.join(epub_images_dir, image_file)
                shutil.copy2(src_path, dst_path)
                print(f"이미지 복사: {image_file}")

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
                    # level2 navPoint들 찾기
                    level2_nav_points = nav_point.findall(f"{{{ncx_ns}}}navPoint")
                    
                    # XHTML 파일 생성
                    xhtml_content = create_xhtml_from_nav_structure(
                        target_element, level2_nav_points, current_file_index, 
                        title, ncx_ns, dtbook_ns, book_title
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
    nav_xhtml = create_nav_xhtml_from_ncx(book_title, nav_points, xhtml_files, ncx_ns)
    
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
    epub_filename = os.path.join(output_dir, f"{book_title.replace(' ', '_')}.epub")
    
    with zipfile.ZipFile(epub_filename, 'w', zipfile.ZIP_DEFLATED) as epub_zip:
        # mimetype 파일 (첫 번째 파일이어야 함, 압축하지 않음)
        epub_zip.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        
        # META-INF/container.xml
        epub_zip.write(os.path.join(output_dir, "META-INF", "container.xml"), "META-INF/container.xml")
        
        # EPUB/package.opf
        epub_zip.write(os.path.join(output_dir, "EPUB", "package.opf"), "EPUB/package.opf")
        
        # EPUB/nav.xhtml
        epub_zip.write(os.path.join(output_dir, "EPUB", "nav.xhtml"), "EPUB/nav.xhtml")
        
        # EPUB/zedai-css.css
        epub_zip.write(os.path.join(output_dir, "EPUB", "zedai-css.css"), "EPUB/zedai-css.css")
        
        # EPUB/zedai-mods.xml
        epub_zip.write(os.path.join(output_dir, "EPUB", "zedai-mods.xml"), "EPUB/zedai-mods.xml")
        
        # EPUB/dtbook-*.xhtml 파일들
        for xhtml_file in xhtml_files:
            epub_zip.write(xhtml_file['filepath'], f"EPUB/{xhtml_file['filename']}")
        
        # EPUB/images/ 파일들
        daisy_images_dir = os.path.join(daisy_dir, "images")
        if os.path.exists(daisy_images_dir):
            for image_file in os.listdir(daisy_images_dir):
                if image_file.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.bmp')):
                    src_path = os.path.join(daisy_images_dir, image_file)
                    epub_zip.write(src_path, f"EPUB/images/{image_file}")
    
    print(f"EPUB3 ZIP 파일 생성 완료: {epub_filename}")
    
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
  <section epub:type="titlepage" role="doc-titlepage">
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

def create_xhtml_from_nav_structure(target_element, level2_nav_points, file_index, title, ncx_ns, dtbook_ns, book_title):
    """NCX 구조를 기반으로 XHTML를 생성합니다."""
    
    # XHTML 시작
    xhtml = f'''<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="ko" lang="ko">

<head>
  <meta charset="UTF-8" />
  <title>{html.escape(book_title)}</title>
  <link rel="stylesheet" type="text/css" href="zedai-css.css" />
</head>

<body xmlns:epub="http://www.idpf.org/2007/ops" epub:type="bodymatter">'''
    
    # level1 섹션 시작
    section_id = target_element.get('id', f'p_{file_index}')
    xhtml += f'''
  <section id="{section_id}">
    <h3 id="id_{file_index + 54}">{html.escape(title)}</h3>'''
    
    # level2 navPoint들 처리
    for level2_nav in level2_nav_points:
        if level2_nav.get('class') == 'level2':
            level2_label = level2_nav.find(f"{{{ncx_ns}}}navLabel")
            level2_content = level2_nav.find(f"{{{ncx_ns}}}content")
            
            if level2_label is not None and level2_content is not None:
                level2_title = level2_label.find(f"{{{ncx_ns}}}text").text if level2_label.find(f"{{{ncx_ns}}}text") is not None else ""
                level2_smil_id = level2_content.get('src', '').split('#')[-1] if '#' in level2_content.get('src', '') else ''
                
                # level2 섹션 추가
                level2_section_id = level2_nav.get('id', '').replace('ncx_', '')
                xhtml += f'''
    <section id="{level2_section_id}">
      <h4 id="id_{file_index + 55}">{html.escape(level2_title)}</h4>'''
                
                # level2 섹션 내용 추가 (여기서는 간단히 제목만 표시)
                xhtml += f'''
      <p>{html.escape(level2_title)}</p>
    </section>'''
    
    # target_element의 내용 처리
    xhtml += process_dtbook_element_content(target_element, dtbook_ns)
    
    # level1 섹션 종료
    xhtml += '''
  </section>
</body>

</html>'''
    
    return xhtml

def process_dtbook_element_content(element, dtbook_ns):
    """DTBook 요소의 내용을 XHTML로 변환합니다."""
    content = ""
    
    for child in element:
        if child.tag.endswith('p'):
            # 단락 처리
            p_id = child.get('id', '')
            p_text = child.text if child.text else ""
            
            # 페이지 번호 처리
            if child.tag.endswith('pagenum'):
                page_num = p_text.strip()
                content += f'''
      <span aria-label=" {page_num}. " role="doc-pagebreak" epub:type="pagebreak" id="page_{page_num}_{page_num}"></span>
      <p id="{p_id}"></p>'''
            else:
                # 일반 단락
                content += f'''
      <p id="{p_id}">{html.escape(p_text)}</p>'''
                
        elif child.tag.endswith('imggroup'):
            # 이미지 그룹 처리
            img_elem = child.find(f"{{{dtbook_ns}}}img")
            if img_elem is not None:
                img_src = img_elem.get('src', '')
                img_alt = img_elem.get('alt', '')
                img_id = img_elem.get('id', '')
                
                # 이미지 파일명 추출
                img_filename = os.path.basename(img_src)
                
                content += f'''
      <figure id="{img_id}">
        <img src="images/{img_filename}" alt="{html.escape(img_alt)}" />
        <figcaption>
          <span id="id_{img_id}">{html.escape(img_alt)}</span>
        </figcaption>
      </figure>'''
                
        elif child.tag.endswith('table'):
            # 표 처리
            table_id = child.get('id', '')
            tbody = child.find(f"{{{dtbook_ns}}}tbody")
            
            if tbody is not None:
                content += f'''
      <table id="{table_id}">'''
                
                for tr in tbody.findall(f"{{{dtbook_ns}}}tr"):
                    content += '''
        <tr>'''
                    for td in tr.findall(f"{{{dtbook_ns}}}td"):
                        cell_text = td.text if td.text else ""
                        content += f'''
          <td>{html.escape(cell_text)}</td>'''
                    for th in tr.findall(f"{{{dtbook_ns}}}th"):
                        cell_text = th.text if th.text else ""
                        content += f'''
          <th>{html.escape(cell_text)}</th>'''
                    content += '''
        </tr>'''
                
                content += '''
      </table>'''
    
    return content

def create_xhtml_from_level1(level1, file_index, dtbook_ns, book_title):
    """level1 요소를 XHTML로 변환합니다."""
    
    # level1의 제목 찾기
    h1_elem = level1.find(f"{{{dtbook_ns}}}h1")
    title = h1_elem.text if h1_elem is not None and h1_elem.text else f"Section {file_index}"
    
    # XHTML 시작
    xhtml = f'''<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="ko" lang="ko">

<head>
  <meta charset="UTF-8" />
  <title>{html.escape(book_title)}</title>
  <link rel="stylesheet" type="text/css" href="zedai-css.css" />
</head>

<body xmlns:epub="http://www.idpf.org/2007/ops" epub:type="bodymatter">
  <section id="p_{level1.get('id', file_index)}">
    <h3 id="id_{file_index + 54}">{html.escape(title)}</h3>'''
    
    # level1 내부의 모든 요소들을 순회
    for elem in level1:
        if elem.tag.endswith('h1'):
            # h1은 이미 처리했으므로 건너뛰기
            continue
        elif elem.tag.endswith('p'):
            # 단락 처리
            p_id = elem.get('id', '')
            p_text = elem.text if elem.text else ""
            
            # 페이지 번호 처리
            if elem.tag.endswith('pagenum'):
                page_num = p_text.strip()
                xhtml += f'''<span aria-label=" {page_num}. " role="doc-pagebreak" epub:type="pagebreak" id="page_{page_num}_{page_num}"></span>
    <p id="{p_id}"></p>'''
            else:
                # 일반 단락
                xhtml += f'''
    <p id="{p_id}">{html.escape(p_text)}</p>'''
                
        elif elem.tag.endswith('imggroup'):
            # 이미지 그룹 처리
            img_elem = elem.find(f"{{{dtbook_ns}}}img")
            if img_elem is not None:
                img_src = img_elem.get('src', '')
                img_alt = img_elem.get('alt', '')
                img_id = img_elem.get('id', '')
                
                # 이미지 파일명 추출
                img_filename = os.path.basename(img_src)
                
                xhtml += f'''
    <figure id="{img_id}">
      <img src="images/{img_filename}" alt="{html.escape(img_alt)}" />
      <figcaption>
        <span id="id_{file_index + 55}">{html.escape(img_alt)}</span>
      </figcaption>
    </figure>'''
                
        elif elem.tag.endswith('table'):
            # 표 처리
            table_id = elem.get('id', '')
            tbody = elem.find(f"{{{dtbook_ns}}}tbody")
            
            if tbody is not None:
                xhtml += f'''
    <table id="{table_id}">'''
                
                for tr in tbody.findall(f"{{{dtbook_ns}}}tr"):
                    xhtml += '''
      <tr>'''
                    for td in tr.findall(f"{{{dtbook_ns}}}td"):
                        cell_text = td.text if td.text else ""
                        xhtml += f'''
        <td>{html.escape(cell_text)}</td>'''
                    for th in tr.findall(f"{{{dtbook_ns}}}th"):
                        cell_text = th.text if th.text else ""
                        xhtml += f'''
        <th>{html.escape(cell_text)}</th>'''
                    xhtml += '''
      </tr>'''
                
                xhtml += '''
    </table>'''
    
    # XHTML 종료
    xhtml += '''
  </section>
</body>

</html>'''
    
    return xhtml

def create_package_opf(book_title, book_author, book_publisher, book_language, book_uid, xhtml_files, daisy_dir):
    """package.opf 파일 내용을 생성합니다."""
    
    # 고유 식별자 생성
    unique_id = str(uuid.uuid4()).replace('-', '')
    
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
              id="item_{i}">'''
    
    # nav.xhtml 추가
    opf += f'''
        <item href="nav.xhtml"
              media-type="application/xhtml+xml"
              id="nav"
              properties="nav">'''
    
    # CSS 파일 추가
    opf += f'''
        <item href="zedai-css.css"
              media-type="text/css"
              id="css">'''
    
    # MODS 파일 추가
    opf += f'''
        <item href="zedai-mods.xml"
              media-type="application/mods+xml"
              id="mods">'''
    
    # 이미지 파일들 추가
    daisy_images_dir = os.path.join(daisy_dir, "images")
    if os.path.exists(daisy_images_dir):
        image_counter = len(xhtml_files) + 4  # XHTML + nav + css + mods
        for image_file in os.listdir(daisy_images_dir):
            if image_file.lower().endswith(('.jpg', '.jpeg')):
                mime_type = "image/jpeg"
            elif image_file.lower().endswith('.png'):
                mime_type = "image/png"
            elif image_file.lower().endswith('.gif'):
                mime_type = "image/gif"
            else:
                continue
                
            opf += f'''
        <item href="images/{image_file}"
              media-type="{mime_type}"
              id="img_{image_counter}">'''
            image_counter += 1
    
    opf += '''
    </manifest>
    <spine>'''
    
    # spine에 XHTML 파일들 추가 (nav.xhtml은 spine에 포함하지 않음)
    for i, xhtml_file in enumerate(xhtml_files, 1):
        opf += f'''
        <itemref idref="item_{i}">'''
    
    opf += '''
    </spine>
</package>'''
    
    return opf

def create_nav_xhtml_from_ncx(book_title, nav_points, xhtml_files, ncx_ns):
    """NCX 구조를 기반으로 nav.xhtml 파일 내용을 생성합니다."""
    
    nav = f'''<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="ko" lang="ko">
<head>
    <meta charset="UTF-8" />
    <title>{html.escape(book_title)}</title>
    <link rel="stylesheet" type="text/css" href="zedai-css.css" />
</head>
<body xmlns:epub="http://www.idpf.org/2007/ops">
    <nav epub:type="toc" role="doc-toc">
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

figure {
    margin: 1em 0;
    text-align: center;
}

figcaption {
    font-style: italic;
    margin-top: 0.5em;
    font-size: 0.9em;
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

/* Page break styling */
[epub\\:type="pagebreak"] {
    display: block;
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
[role="doc-pagebreak"] {
    display: none;
}

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
