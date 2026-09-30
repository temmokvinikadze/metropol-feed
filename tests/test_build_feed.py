"""Offline test: fake /results pages in the same RSC format metropol.ge serves."""
import json
import os
import sys
import tempfile
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import build_feed as bf  # noqa: E402

FLATS = [
    {"id": "a", "flatID": "41313", "projectID": "ქავთარაძე", "buildingName": "A1", "flatNum": "1609",
     "flatStatus": "თავისუფალი", "flatTypeName": "residential", "flatTypeNameInvestment": "საცხოვრებელი",
     "floor": 16, "price": 239333.5, "kvmPrice": "2065", "WHOLE_AREA": 115.9, "LIVING_AREA": "99.2",
     "BALCONY_AREA": "16.7", "BEDROOM": "2", "render": "https://crm.metropol.ge/upload/x.jpg",
     "city": "თბილისი", "view": "", "projectFinishDate": "30/06/2027", "flatDiscrGE": "", "flatDiscrEN": ""},
    {"id": "b", "flatID": "31241", "projectID": "ბათუმი OVAL", "buildingName": "O1", "flatNum": "3114",
     "flatStatus": "თავისუფალი", "flatTypeName": "აპარტამენტი", "flatTypeNameInvestment": "საინვესტიციო",
     "floor": 31, "price": 90405, "kvmPrice": "2870", "WHOLE_AREA": 31.5, "LIVING_AREA": "25.7",
     "BALCONY_AREA": "5.8", "BEDROOM": "სტუდიო", "render": "", "city": "ბათუმი",
     "view": "Sea, The Alley & <Park>", "projectFinishDate": "31/12/2027"},
    {"id": "c", "flatID": "121484", "projectID": "ორთაჭალა", "buildingName": "", "flatNum": "381",
     "flatStatus": "თავისუფალი", "flatTypeName": "parking", "floor": 3, "price": 15000, "WHOLE_AREA": 12.5,
     "city": "თბილისი"},
    {"id": "d", "flatID": "999", "projectID": "ქავთარაძე", "buildingName": "A2", "flatNum": "1",
     "flatStatus": "გაყიდული", "flatTypeName": "residential", "floor": 1, "price": 1, "WHOLE_AREA": 1,
     "city": "თბილისი"},
]


def page(titles):
    projects = [{"title": t, "projectId": pid, "slug": s} for pid, t, s in titles]
    body = json.dumps({"projects": projects, "apartments": FLATS}, ensure_ascii=False)
    chunk = '5:["$","$L1a",null,' + body + "]\n"
    half = len(chunk) // 2  # split across two pushes, like Next.js streaming
    pushes = "".join(
        f"<script>self.__next_f.push({json.dumps([1, c], ensure_ascii=False)})</script>"
        for c in (chunk[:half], chunk[half:])
    )
    return "<html><body><script>self.__next_f.push([0])</script>" + pushes + "</body></html>"


KA = page([("ქავთარაძე", "ქავთარაძე", "kavtaradze"), ("ბათუმი OVAL", "ოვალი", "batumi-oval"),
           ("ორთაჭალა", "ორთაჭალა", "ortachala")])
EN = page([("ქავთარაძე", "Kavtaradze", "kavtaradze"), ("ბათუმი OVAL", "Oval", "batumi-oval"),
           ("ორთაჭალა", "Ortachala", "ortachala")])


def fake_fetch(url):
    if url.endswith("/en/results"):
        return EN
    if url.endswith("/results"):
        return KA
    if url.endswith("/api/rate"):
        return '{"usdRate":2.6051}'
    raise AssertionError(url)


def main():
    bf.fetch = fake_fetch
    bf.MIN_ITEMS = 1
    ns = {"g": "http://base.google.com/ns/1.0"}
    with tempfile.TemporaryDirectory() as d:
        assert bf.main(d) == 0
        for name in ("feed.xml", "feed_en.xml"):
            root = ET.parse(os.path.join(d, name)).getroot()
            items = root.findall("./channel/item")
            assert len(items) == 2, (name, len(items))  # parking + sold excluded
            for it in items:
                print(name, "|", it.find("g:id", ns).text, "|", it.find("g:title", ns).text, "|",
                      it.find("g:price", ns).text, "|", it.find("g:link", ns).text, "|",
                      it.find("g:image_link", ns).text)
            print("  desc:", items[0].find("g:description", ns).text)
        ka = open(os.path.join(d, "feed.xml"), encoding="utf-8").read()
        assert "batumi-oval-o1/floor-31/apartment-3114" in ka
        assert "metropol-oval-6uLFk27" in ka  # fallback image used
        assert "&amp;" in ka and "&lt;Park&gt;" in ka
    print("OK")


if __name__ == "__main__":
    main()
