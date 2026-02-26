import docx
import sys

doc = docx.Document('六祖坛经.docx')
lines = [p.text for p in doc.paragraphs if p.text.strip()]
with open('sutra.txt', 'w', encoding='utf-8') as f:
    for line in lines:
        f.write(line + '\n')
print('Done, total paragraphs:', len(lines))
