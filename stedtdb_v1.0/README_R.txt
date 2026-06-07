BABY STEPS TOWARDS USING THE STEDT DATABASE AS AN R DATAFRAME

v1.0 11 June 2017

The denormalized file (_denormalized-lexicon_20161229.csv) can be loaded straightforwardly into R.

The result is a dataframe with one row per lexical item per language.  Note that this includes "protoforms"
in proto- and meso-languages as well.

Caveat: it seems there are a few characters in the STEDT data that R does not like. To fix them try:

perl -pe 's/["’#]//g;' STEDT_denormalized-lexicon_20161229.csv | perl -pe "s/'//g" > fixed.csv

Then, in R:

$ R
R version 3.3.0 (2016-05-03) -- "Supposedly Educational"
[....]

# how to load the denormalized stedt data into an r data frame
> filename = "fixed.csv"
> STEDTdata <- read.table(filename, sep="\t", header=TRUE)
# 12 columns (see below)
> length(STEDTdata)
[1] 12
# 530,408 lexical items
> nrow(STEDTdata)
[1] 530408
> save.image(file = "STEDTfile.RData")
> q()

# restart r, load the save data frame
$ R

> load("STEDTfile.RData")
# here are the name of the columns
> colnames(STEDTdata)
 [1] "rn"        "language"  "form"      "gloss"     "gfn"       "semkey"   
 [7] "analysis"  "groupnode" "subgroup"  "srcabbr"   "citation"  "srcid" 

# for some languages, there is a lot of data, for others only a bit...   
> aggregate(rn ~ language, STEDTdata, function(x) length(unique(x)))
                                         language    rn
1                                                     1
2                                             *Ao   386
3                                        *Asakian     2
4                                     *Austro-Tai     3
5                                        *Bah-Sun     3
6                                         *Barish     4

[snip]

58                                         Achang     3
59                               Achang (Lianghe)   991
60                             Achang (Longchuan)  2800
61                                  Achang (Luxi)   998
62                               Achang (Xiandao)  1749

[snip]

684                                     Yi (Xide)  3597
685                                          Yidu   969
686                                    Yimchungrü   990
687                                          Zeme   923
688                                  Zerungge Rai     2
689                          Zhaba (Daofu County)  1877
690                                    Zhangzhung     5
691                                        Zotung    86
