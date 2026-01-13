import sys
sys.path.insert(0, 'c:/source/refchecker/src')

from refchecker.utils.text_utils import extract_latex_references

bbl_content = r'''
\begin{thebibliography}{X}

\bibitem[Test20]{test2020}
Author Name.
\newblock Test Paper Title.
\newblock In {\em International Conference on Robotics and Automation}, 2020.

\end{thebibliography}
'''

refs = extract_latex_references(bbl_content)
if refs:
    ref = refs[0]
    print(f"Title: {ref.get('title', 'NOT SET')}")
    print(f"Authors: {ref.get('authors', 'NOT SET')}")
    print(f"Year: {ref.get('year', 'NOT SET')}")
    print(f"Journal: {ref.get('journal', 'NOT SET')}")
    print(f"Venue: {ref.get('venue', 'NOT SET')}")
    print(f"All keys: {list(ref.keys())}")
else:
    print("No references extracted")
