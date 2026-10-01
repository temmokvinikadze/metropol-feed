# Metropol – Meta catalog feed

metropol.ge-ის თავისუფალი ბინებისა და აპარტამენტების ავტომატურად განახლებადი XML ფიდი Meta Commerce Manager-ისთვის (Facebook / Instagram Advantage+ Catalog Ads).

## როგორ მუშაობს

- `scripts/build_feed.py` კითხულობს `https://www.metropol.ge/results` გვერდს. ამ გვერდზე მთელი მარაგია ჩაშენებული.
- ფიდში შედის მხოლოდ **ქავთარაძისა და ორთაჭალის** პროექტების **თავისუფალი** ობიექტები, რომელთა ტიპია `residential` ან `აპარტამენტი`. პარკინგი, მიწა, ოფისი და კომერციული ფართი არ შედის.
- GitHub Action ყოველ 4 საათში ერთხელ ეშვება. თუ მარაგი შეიცვალა, ახალ `feed.xml` / `feed_en.xml`-ს commit-ით ინახავს.
- გაყიდული ბინა ფიდიდან ავტომატურად ქრება, ხოლო Meta scheduled feed-ის განახლებისას მას კატალოგიდანაც შლის.
- თუ საიტის სტრუქტურა შეიცვალა და 50-ზე ნაკლები ობიექტი მოიძებნა, ფიდი **არ** გადაიწერება. ძველი რჩება და Action წითლად ჩავარდება, GitHub კი მეილს გამოგიგზავნის.

## ფიდის ბმულები (Meta-ში ჩასასმელად)

```
https://raw.githubusercontent.com/<OWNER>/<REPO>/main/feed.xml      ← ქართული
https://raw.githubusercontent.com/<OWNER>/<REPO>/main/feed_en.xml   ← English
```

რეპო უნდა იყოს **public**, რომ Meta-მ ფაილი წაიკითხოს.

## Meta-ში დაკავშირება

1. Commerce Manager → **Catalog** → Data sources → **Add items** → **Data feed** → *Use a URL*.
2. ჩასვი ზემოთ მოცემული ბმული. Currency: **GEL**.
3. Schedule: **Hourly** ან **Daily**. რადგან Action 4 საათში ერთხელ ეშვება, Daily-ც საკმარისია.
4. Upload type: **Replace** (default). ასე გაყიდული ობიექტები კატალოგიდან თავისით წაიშლება.

## ველები

| ველი | მნიშვნელობა |
|---|---|
| `id` | `MP-<flatID>` CRM-იდან |
| `title` | „2-საძინებლიანი ბინა, 115.9 მ² – ქავთარაძე, თბილისი“ |
| `price` | ფასი ლარში: CRM-ის USD ფასი გადაყვანილი საიტის `/api/rate` კურსით, დამრგვალებული (როგორც საიტზე ჩანს) |
| `link` | ბინის კონკრეტული გვერდი საიტზე |
| `image_link` | პროექტის რენდერი (JPG-ად გადაყვანილი, `images/` საქაღალდიდან). ბინებზე რენდერები მონაცვლეობით ნაწილდება |
| `additional_image_link` | დანარჩენი რენდერები + ბინის გეგმა |
| `custom_label_0..4` | პროექტი / ქალაქი / საძინებლები / ფასის დიაპაზონი / დანიშნულება (საინვესტიციო, საცხოვრებელი). Product set-ების ფილტრებისთვის |

## ცვლილებები

- **ფასი დოლარში:** `.github/workflows/update-feed.yml`-ში შეცვალე `PRICE_CURRENCY: USD`.
- **პროექტების შეცვლა:** workflow-ში `INCLUDE_PROJECTS` (slug-ები: `kavtaradze`, `ortachala`, `parallel`, `batumi-cube`, `batumi-oval`, `lisi`, `shindisi`, `bagebi`). ცარიელი = ყველა.
- **სხვა ტიპების დამატება:** `scripts/build_feed.py`-ში შეცვალე `INCLUDE_TYPES`.
- **ხელით განახლება:** Actions → *Update Meta catalog feed* → **Run workflow**.

- **რენდერების შეცვლა:** `scripts/build_feed.py`-ში `PROJECT_RENDERS` — თითო პროექტზე საიტის `/uploads/...` ბმულების სია.
