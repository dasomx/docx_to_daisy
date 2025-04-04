import zipfile
import os
import uuid
import argparse
from docx import Document  # python-docx 라이브러리
from lxml import etree  # lxml 라이브러리
from datetime import datetime


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

    book_uid = f"AUTO-UID-{uuid.uuid4().int}"  # 고유 식별자

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

    # DOCX의 단락(paragraph)을 순회하며 구조 파악
    print("DOCX 파일 분석 중...")
    for para in document.paragraphs:
        text = para.text.strip()
        if not text:  # 내용이 없는 단락은 건너뜀
            continue

        element_counter += 1
        elem_id = f"id_{element_counter}"
        style_name = para.style.name.lower()  # 스타일 이름을 소문자로 비교

        # 스타일 이름에 따른 구조 매핑
        if style_name.startswith('heading 1') or style_name == '제목 1':
            content_structure.append(
                {"type": "h1", "text": text, "id": elem_id, "level": 1})
        elif style_name.startswith('heading 2') or style_name == '제목 2':
            content_structure.append(
                {"type": "h2", "text": text, "id": elem_id, "level": 2})
        elif style_name.startswith('heading 3') or style_name == '제목 3':
            content_structure.append(
                {"type": "h3", "text": text, "id": elem_id, "level": 3})
        else:  # 기본적으로 'p' (문단)으로 처리
            content_structure.append(
                {"type": "p", "text": text, "id": elem_id, "level": 0})

    print(f"총 {len(content_structure)}개의 구조 요소 분석 완료.")

    # --- 1. DTBook XML 생성 (dtbook.xml) ---
    print("DTBook 생성 중...")
    dtbook_ns = "http://www.daisy.org/z3986/2005/dtbook/"

    dtbook_root = etree.Element(
        "{%s}dtbook" % dtbook_ns,
        attrib={
            "version": "2005-3"
        },
        nsmap={
            None: dtbook_ns
        }
    )

    # head 요소 추가 (비어있음)
    etree.SubElement(dtbook_root, "head")

    # book 요소 추가
    dtbook_book = etree.SubElement(dtbook_root, "book")

    # frontmatter 추가
    dtbook_frontmatter = etree.SubElement(dtbook_book, "frontmatter")
    doctitle = etree.SubElement(dtbook_frontmatter, "doctitle", id="forsmil-1")
    doctitle.text = book_title

    # bodymatter 추가
    dtbook_bodymatter = etree.SubElement(dtbook_book, "bodymatter")

    # 콘텐츠 추가
    for item in content_structure:
        elem_id = item["id"]
        text = item["text"]

        if item["type"].startswith("h"):
            level = etree.SubElement(
                dtbook_bodymatter, f"level{item['level']}")
            heading = etree.SubElement(level, f"h{item['level']}", id=elem_id)
            heading.text = text
        else:
            p = etree.SubElement(dtbook_bodymatter, "p", id=elem_id)
            p.text = text

    # XML 파일 저장
    dtbook_filepath = os.path.join(output_dir, "dtbook.xml")
    tree = etree.ElementTree(dtbook_root)

    with open(dtbook_filepath, 'wb') as f:
        f.write(b'<?xml version="1.0" encoding="UTF-8"?>\n')
        tree.write(f,
                   pretty_print=True,
                   encoding='UTF-8',
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

    # SMIL
    etree.SubElement(manifest, "item",
                     href="mo0.smil",
                     id="mo0",
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
                     idref="mo0")

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

    # --- 3. SMIL 파일 생성 (mo0.smil) ---
    print("SMIL 생성 중...")
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

    # customAttributes
    custom_attrs = etree.SubElement(head, "customAttributes")
    custom_tests = [
        ("pagenum", "page"),
        ("note", "note"),
        ("noteref", "note"),
        ("annotation", "annotation"),
        ("linenum", "line"),
        ("sidebar", "sidebar"),
        ("prodnote", "note")
    ]

    for test_id, _ in custom_tests:
        etree.SubElement(custom_attrs, "customTest",
                         id=test_id,
                         defaultState="false",
                         override="visible")

    # body
    body = etree.SubElement(smil_root, "body")
    root_seq = etree.SubElement(body, "seq", id="root-seq")

    # doctitle
    doctitle_par = etree.SubElement(root_seq, "par",
                                    id="sforsmil-1",
                                    **{"class": "doctitle"})
    etree.SubElement(doctitle_par, "text",
                     src="dtbook.xml#forsmil-1")

    # 콘텐츠
    for i, item in enumerate(content_structure, start=1):
        seq = etree.SubElement(root_seq, "seq",
                               id=f"s{item['id']}",
                               **{"class": item["type"]})
        par = etree.SubElement(seq, "par",
                               id=f"p{item['id']}",
                               **{"class": "sent"})
        etree.SubElement(par, "text",
                         src=f"dtbook.xml#{item['id']}")

    # SMIL 파일 저장
    smil_filepath = os.path.join(output_dir, "mo0.smil")
    tree = etree.ElementTree(smil_root)

    with open(smil_filepath, 'wb') as f:
        f.write(b'<?xml version="1.0" encoding="utf-8"?>\n')
        f.write(b'<!DOCTYPE smil\n  PUBLIC "-//NISO//DTD dtbsmil 2005-2//EN" "http://www.daisy.org/z3986/2005/dtbsmil-2005-2.dtd">\n')
        tree.write(f,
                   pretty_print=True,
                   encoding='utf-8',
                   xml_declaration=False)

    print(f"SMIL 생성 완료: {smil_filepath}")

    # --- 4. Resources 파일 생성 (resources.res) ---
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
