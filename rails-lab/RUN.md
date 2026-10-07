# Rails lab: model eval (made-up cases only, no personal text)
Step 1 (tiny check):  python3 lab.py run --roles 9 --models plan:haiku --workers 2 --force ; python3 lab.py summary
Step 2 (full Claude eval, only when told): python3 lab.py run --roles all --models plan:opus,plan:sonnet,plan:haiku --workers 4 --force ; python3 lab.py summary ; python3 lab.py combos <run-id> --size 2
