"""
The ten syllabuses of the Eduport Plus "Plan & Price" PDFs, transcribed from
them (D8) for ``manage.py load_reference_syllabi``, which loads them as drafts
for the Admin to review against those PDFs before publishing. Chapter names
are as the PDFs show them, their slips included ("A Peak Beyond the Point",
"Finding The Unkowns"): correcting them is the review's job. The PDFs' "←>"
is written "↔". Each is a SyllabusContentSerializer payload, with the file
name of the PDF it comes from under ``source`` (which the serializer ignores):
a loaded syllabus keeps it as its reference_key.
"""

INCLUSIONS = ['Personalized 1:1 live sessions', 'Structured CBSE aligned learning', 'Dedicated mentor support']
# What the chapter-wise PDFs sell: a Regular and a Revision package (D6).
CHAPTER_WISE_PLANS = ['REGULAR', 'REVISION', 'REGULAR_REVISION']


def _chapter_wise(source, title, grade, version, rows, package_title=None):
    return {
        'source': source,
        'title': title,
        'package_title': package_title or '',
        'grade': grade,
        'board': 'CBSE',
        'syllabus_version': version,
        'structure': 'CHAPTER_WISE',
        'plan_types': CHAPTER_WISE_PLANS,
        'inclusions': INCLUSIONS,
        'chapters': [
            {'name': name, 'regular_classes': str(regular), 'revision_classes': str(revision)}
            for name, regular, revision in rows
        ],
    }


def _bridge(source, title, grade, days):
    return {
        'source': source,
        'title': title,
        'grade': grade,
        'board': 'CBSE',
        'syllabus_version': '',
        'structure': 'BRIDGE_COURSE',
        'plan_types': ['BRIDGE_COURSE'],
        'inclusions': INCLUSIONS,
        'chapters': [{'name': name, 'bridge_classes': '1'} for name in days],
    }


REFERENCE_SYLLABI = [
    # 6th (New Syllabus) Plan & Price.pdf -- 38 Regular, 19 Revision
    _chapter_wise('6th (New Syllabus)  Plan & Price.pdf', 'Grade 6 CBSE', 6, 'New Syllabus', [
        ('Patterns In Mathematics', 4, 2),
        ('Lines And Angles', 5, 2),
        ('Number Play', 4, 2),
        ('Data Handling And Presentation', 3, 2),
        ('Prime Time', 3, 2),
        ('Perimeter And Area', 3, 2),
        ('Fractions', 5, 2),
        ('Playing With Constructions', 4, 2),
        ('Symmetry', 2, 1),
        ('The Other Side Of Zero', 5, 2),
    ]),
    # 6th (Old Syllabus) Plan & Price.pdf -- 41 Regular, 21 Revision
    _chapter_wise('6th (Old Syllabus) Plan & Price.pdf', 'Grade 6 CBSE (Old Syllabus)', 6, 'Old Syllabus', [
        ('Knowing Our Numbers', 3, 2),
        ('Whole Numbers', 3, 2),
        ('Playing With Numbers', 3, 2),
        ('Basic Geometrical Ideas', 2, 1),
        ('Understanding Elementary Shapes', 2, 1),
        ('Integers', 3, 2),
        ('Fractions', 4, 2),
        ('Decimals', 4, 2),
        ('Data Handling', 3, 1),
        ('Mensuration', 3, 1),
        ('Algebra', 4, 2),
        ('Ratio And Proportion', 2, 1),
        ('Symmetry', 3, 1),
        ('Practical Geometry', 2, 1),
    ], package_title='Grade 6 CBSE – 1:1 Tuition Packages & Fee Details'),
    # 7th (New Syllabus) Plan & Price.pdf -- 43 Regular, 26 Revision
    _chapter_wise('7th (New Syllabus) Plan & Price.pdf', 'Grade 7 CBSE', 7, 'New Syllabus', [
        ('Large Numbers Around Us', 3, 2),
        ('Arithmetic Expressions', 3, 2),
        ('A Peak Beyond The Point', 4, 2),
        ('Expressions Using Letter Numbers', 3, 2),
        ('Parallel And Intersecting Lines', 3, 1),
        ('Number Play', 3, 2),
        ('A Tail Of Three Intersecting Lines', 3, 1),
        ('Working With Fractions', 3, 2),
        ('Geometric Twins', 3, 2),
        ('Operations With Integers', 3, 2),
        ('Finding Common Ground', 3, 2),
        ('Another Peak Beyond The Point', 2, 2),
        ('Connecting The Dots', 2, 1),
        ('Constructions And Tilings', 2, 1),
        ('Finding The Unkowns', 3, 2),
    ]),
    # 7th (Old Syllabus) Plan & Price.pdf -- 39 Regular, 22 Revision
    _chapter_wise('7th (Old Syllabus) Plan & Price.pdf', 'Grade 7 CBSE (Old Syllabus)', 7, 'Old Syllabus', [
        ('Integers', 3, 2),
        ('Fractions And Decimals', 4, 2),
        ('Data Handling', 2, 1),
        ('Simple Equations', 3, 1),
        ('Lines And Angles', 3, 2),
        ('Triangles And Its Properties', 3, 2),
        ('Comparing Quantities', 3, 2),
        ('Rational Numbers', 3, 2),
        ('Perimeter And Area', 4, 2),
        ('Algebraic Equations', 4, 2),
        ('Exponents And Powers', 3, 2),
        ('Symmetry', 2, 1),
        ('Visualizing Solid Shapes', 2, 1),
    ], package_title='Grade 7 CBSE – 1:1 Tuition Packages & Fee Details'),
    # 8th (New Syllabus) Plan & price.pdf -- 43 Regular, 26 Revision
    _chapter_wise('8th (New Syllabus) Plan & price.pdf', 'Grade 8 CBSE', 8, 'New Syllabus', [
        ('A Square And A Cube', 2, 1),
        ('Power Play', 4, 2),
        ('A Story Of Numbers', 3, 2),
        ('Quadrilaterals', 3, 2),
        ('Number Play', 3, 2),
        ('We Distribute, Yes Things Multiply', 3, 2),
        ('Proportional Reasoning', 3, 2),
        ('Fractions In Disguise', 4, 2),
        ('The Baudhayana-Pythagoras Theorem', 3, 2),
        ('Proportional Reasoning - 2', 2, 1),
        ('Exploring Some Geometric Themes', 3, 2),
        ('Tales By Dot And Lines', 3, 2),
        ('Algebra Play', 3, 2),
        ('Area', 4, 2),
    ]),
    # 8th (Old Syllabus) Plan & price.pdf -- 39 Regular, 21 Revision
    _chapter_wise('8th (Old Syllabus) Plan & price.pdf', 'Grade 8 CBSE (Old Syllabus)', 8, 'Old Syllabus', [
        ('Rational Numbers', 3, 2),
        ('Linear Equations In One Variable', 3, 2),
        ('Understanding Quadrilaterals', 3, 2),
        ('Data Handling', 2, 1),
        ('Square And Square Roots', 3, 1),
        ('Cube And Cube Roots', 2, 1),
        ('Comparing Quantities', 3, 1),
        ('Algebraic Expressions And Identities', 3, 2),
        ('Mensuration', 4, 2),
        ('Exponents And Powers', 3, 2),
        ('Direct And Inverse Proportions', 4, 2),
        ('Factorization', 4, 2),
        ('Introduction To Graphs', 2, 1),
    ], package_title='Grade 8 CBSE – 1:1 Tuition Packages & Fee Details'),
    # 9th Plan & Price.pdf -- 79 Regular, 41 Revision
    _chapter_wise('9th Plan & Price.pdf', 'Grade 9 CBSE', 9, '', [
        ('Coordinate Geometry', 4, 2),
        ('Introduction To Polynomials', 5, 3),
        ('Number System', 7, 4),
        ('Introduction To Euclid’s Geometry: Axioms And Postulates', 2, 1),
        ('Lines And Angles', 5, 3),
        ('Sequences And Progressions', 5, 3),
        ('Triangles: Congruence Theorems', 4, 2),
        ('Mensuration: Area And Perimeter', 7, 4),
        ('Exploring Algebraic Identities', 5, 3),
        ('4 - Gons', 7, 3),
        ('Circles', 7, 3),
        ('Linear Equations In Two Variables', 7, 3),
        ('Surface Areas And Volumes', 4, 2),
        ('Statistics', 5, 3),
        ('Probability', 5, 2),
    ]),
    # 10th Plan & Price.pdf -- 72 Regular, 30 Revision (half revision classes)
    _chapter_wise('10th Plan & Price.pdf', 'Grade 10 CBSE', 10, '', [
        ('Real Numbers', 4, '1.5'),
        ('Polynomials', 4, 2),
        ('Pair Of Linear Equations', 6, '2.5'),
        ('Quadratic Equation', 6, 3),
        ('Arithmetic Progression', 6, 3),
        ('Triangles', 6, 2),
        ('Coordinate Geometry', 4, 2),
        ('Introduction To Trigonometry', 7, 3),
        ('Applications Of Trigonometry', 4, 2),
        ('Circles', 7, 3),
        ('Area Related To Circles', 4, 1),
        ('Surface Areas And Volumes', 6, 3),
        ('Statistics', 4, 1),
        ('Probability', 4, 1),
    ]),
    # 7th Grade Bridge Course.pdf -- 30 days of one class
    _bridge('7th Grade Bridge Course.pdf', 'Grade 7 CBSE', 7, [
        'Addition Subtraction Word Problem',
        'Multiplication Word Problem',
        'Division ,BODMAS,Word Problem',
        'Fraction, Types Of Fractions, Conversions (Improper ↔ Mixed)',
        'Fractions Addition And Subtraction',
        'Multiplication And Division Of Fractions',
        'Decimal Introduction Addition Subtraction',
        'Decimal Multiplication And Division',
        'Conversion (Fractions ↔ Decimals)',
        'Fractions And Decimals Word Problems',
        'Ratios',
        'Percentage',
        'Factors And Multiples, Prime And Composite Numbers',
        'Factorization',
        'LCM And HCF',
        'LCM And HCF Word Problems',
        'Number System Introduction (N,W,Z)',
        'Negative Numbers',
        'Negative Numbers',
        'Lines And Angles',
        'Construction Of Angles',
        'Triangles',
        'Polygons Perimeter And Area Of Triangle',
        'Rectangle And Square',
        'Word Problems Related To Area And Perimeter',
        'Circle And It’s Construction',
        'Construction Of Rectangle And Square',
        'Time',
        'Unit Conversion',
        'Unit Conversion',
    ]),
    # 9th Grade Bridge Course.pdf -- 30 days of one class
    _bridge('9th Grade Bridge Course.pdf', 'Grade 9 CBSE', 9, [
        'Types Of Numbers (Natural, Whole, Integers, Rational, And An Intro To Irrationals).',
        'Mastery Of Integers (Rules For Addition, Subtraction, Multiplication And Division With Negative Numbers).',
        'Fractions & Decimals: Advanced Operations And Complex Word Problems.',
        'The Number Line: Representing Fractions And Decimals Accurately.',
        'Divisibility Rules, Prime Factorization, And The Relationship Between HCF And LCM.',
        'Squares, Cubes, And Roots (Estimating And Calculating Square Roots).',
        'Laws Of Exponents (Essential For 9th-Grade Algebra).',
        'Introduction To Variables: Algebraic Expressions Vs. Equations.',
        'Operations On Algebraic Expressions (Addition And Subtraction Of Like Terms).',
        'Polynomial Basics: Identifying Terms, Coefficients, And Degrees.',
        'Linear Equations In One Variable (Solving For X).',
        'Linear Equations Word Problems (Translating English To Math).',
        'Introduction To Cartesian Plane (Plotting Points (X, Y)—Essential For Coordinate Geometry)',
        'Ratios, Proportions, And Unitary Method',
        'Percentages: Conversions And Foundational Calculations',
        'Profit, Loss, And Discount.',
        'Simple Interest Vs. Compound Interest (Introductory Concept).',
        'Lines And Angles: Complementary, Supplementary, And Transversals.',
        'Triangle Properties: Angle Sum Property And Exterior Angle Theorem',
        'Congruence Of Triangles (Introduction To SSS, SAS, ASA, RHS).',
        'Quadrilaterals: Properties Of Parallelograms, Rhombus, And Trapeziums',
        'Circles: Terminology (Chord, Segment, Sector, Tangent).',
        'Geometric Constructions: Bisecting Angles And Lines.',
        "Perimeter And Area: Triangles (Heron's Formula Intro) And Quadrilaterals.",
        'Circle: Circumference And Area.',
        'Surface Area And Volume: Cubes, Cuboid, Cone, Cylinders, Spheres.',
        'Data Handling: Mean, Median, And Mode (Central Tendency).',
        'Introduction To Probability: Basic Outcomes And Events.',
        'Mastery Of Unit Conversions (Length, Area, Volume, And Time).',
        'Unit Conversion Then After Comprehensive Review & "9th Standard Sneak Peek" (Mock Assessment).',
    ]),
]

# Each reference PDF's chapter totals, as its table states them: a check on the transcription.
REFERENCE_TOTALS = [
    {'regular': '38', 'revision': '19', 'bridge': '0'},
    {'regular': '41', 'revision': '21', 'bridge': '0'},
    {'regular': '43', 'revision': '26', 'bridge': '0'},
    {'regular': '39', 'revision': '22', 'bridge': '0'},
    {'regular': '43', 'revision': '26', 'bridge': '0'},
    {'regular': '39', 'revision': '21', 'bridge': '0'},
    {'regular': '79', 'revision': '41', 'bridge': '0'},
    {'regular': '72', 'revision': '30', 'bridge': '0'},
    {'regular': '0', 'revision': '0', 'bridge': '30'},
    {'regular': '0', 'revision': '0', 'bridge': '30'},
]
