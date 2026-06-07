Notes: STEDT denormalized tables

v1.0 11 June 2017

These two csv files consitute a semi-denormalized version of the most relevant portions of the STEDT database. (A full dump of the MySQL database is provided in the sql file, STEDT_public_20160602.sql.bz2.)

The script that creates these denormalized versions may be found in GitHub:

   https://github.com/stedt-project/sss/blob/master/archiving/dump/gen_denorm.pl

The fields are tab-separated, and there is no "encapsulation" -- that is, the values are in no case enclosed in quotes.

ETYMA

The etyma csv file (STEDT_denormalized-etyma_20161229.csv) contains the following fields for each reconstruction:

	tag: Unique id for the etymon.
	plg: Proto-language abbreviation.
	protoform: Reconstructed form.
	protogloss: Reconstructed gloss(es).
	notes: Some scattered notes on the etymon.
	semkey: Position in the semantic hierarchy.

LEXICON

The lexicon csv file (STEDT_denormalized-lexicon_20161229.csv) contains the following fields for each lexical item:

	rn: "record number" - Unique id for the lexicon record.
	language: Language of the lexical item.
	form: Transcribed form (including STEDT delimiters: ◦ [inserts morpheme break] and | [overrides original morpheme break]).
	gloss: English gloss.
	gfn: Grammatical category of the record.
	semkey: Position in the semantic hierarchy.
	analysis: Etymological analysis for each morpheme (#=etyma tag, m=morpheme, s=suffix, p=prefix, b=borrowing, bLANGUAGE=borrowing from LANGUAGE)
	subgroup: Group number and name of subgroup to which language belongs.
	srcabbr: Abbreviation for bibliographic source of lexical item.
	citation: Short citation form of bibliographic source.
	srcid: Location of lexical item in source (set number/page number/etc.).