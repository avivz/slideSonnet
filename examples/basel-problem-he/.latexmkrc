# Keep LaTeX intermediates (.aux, .log, .nav, ...) out of the deck directory.
# The PDF still lands next to the .tex source, where slidesonnet expects it.
$aux_dir = '.build';
$emulate_aux = 1;  # TeX Live pdflatex has no -aux-directory; latexmk emulates it
