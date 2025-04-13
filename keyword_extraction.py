import re
import nltk
from collections import defaultdict
from nltk.corpus import wordnet, stopwords
from nltk.tokenize import word_tokenize, sent_tokenize
from nltk.tag import pos_tag
from nltk.stem import WordNetLemmatizer

# Initialize NLP resources
nltk.download(['punkt', 'averaged_perceptron_tagger',
              'wordnet', 'stopwords'], quiet=True)
lemmatizer = WordNetLemmatizer()
stop_words = set(stopwords.words('english'))


def infer_topics(name, description, n=10):
    """Infer relevant but unmentioned topics using pure linguistic analysis"""
    text = f"{name} {description}".lower()

    # Step 1: Extract core concepts
    core_concepts = extract_core_concepts(text)

    # Step 2: Build semantic network
    semantic_network = build_semantic_network(core_concepts)

    # Step 3: Score and filter inferred topics
    inferred_topics = score_and_filter(semantic_network, core_concepts, n)

    return inferred_topics


def extract_core_concepts(text):
    """Extract key noun phrases using syntactic patterns"""
    grammar = r"""
        NP: {<DT|PP\$>?<JJ.*>*<NN.*>+}  # Noun phrases
        ENT: {<NNP>+}                   # Named entities
    """
    chunker = nltk.RegexpParser(grammar)

    concepts = set()
    for sentence in sent_tokenize(text):
        words = word_tokenize(sentence)
        tagged = pos_tag(words)
        tree = chunker.parse(tagged)

        for subtree in tree.subtrees():
            if subtree.label() in ['NP', 'ENT']:
                phrase = normalize_phrase(
                    ' '.join(word for word, tag in subtree.leaves()))
                if is_valid_concept(phrase):
                    concepts.add(phrase)
    return concepts


def normalize_phrase(phrase):
    """Normalize phrases through lemmatization and cleaning"""
    words = [lemmatizer.lemmatize(word)
             for word in word_tokenize(phrase)
             if word not in stop_words and len(word) > 2]
    return ' '.join(words)


def is_valid_concept(phrase):
    """Validate concept quality using linguistic criteria"""
    words = phrase.split()
    return (3 <= len(phrase) <= 25 and
            not any(word in {'something', 'thing', 'way'} for word in words) and
            not phrase.endswith(('ing', 'tion', 'ment')))


def build_semantic_network(concepts):
    """Build network of related concepts using WordNet"""
    network = defaultdict(set)

    for concept in concepts:
        base_word = max(concept.split(), key=len)  # Most significant word

        for synset in wordnet.synsets(base_word, pos='n')[:3]:
            # Get more specific concepts (hyponyms)
            for hypo in synset.hyponyms()[:2]:
                for lemma in hypo.lemmas()[:2]:
                    related = lemma.name().replace('_', ' ')
                    if is_valid_concept(related):
                        network[concept].add(related)

            # Get broader categories (hypernyms)
            for hyper in synset.hypernyms()[:2]:
                for lemma in hyper.lemmas()[:2]:
                    related = lemma.name().replace('_', ' ')
                    if is_valid_concept(related):
                        network[concept].add(related)

    return network


def score_and_filter(network, core_concepts, n):
    """Score and filter inferred topics"""
    mentioned_words = {
        word for concept in core_concepts for word in concept.split()}
    scored = defaultdict(int)

    for source, related in network.items():
        for concept in related:
            # Only consider unmentioned concepts
            if not any(word in mentioned_words for word in concept.split()):
                # Score based on specificity
                scored[concept] += len(concept.split())  # Multi-word bonus
                if any(tag.startswith('NNP') for _, tag in pos_tag(word_tokenize(concept))):
                    scored[concept] += 3  # Proper noun bonus

    # Remove duplicates and sort
    unique = {}
    for concept, score in sorted(scored.items(), key=lambda x: (-x[1], x[0])):
        norm = ' '.join(sorted(concept.split()))
        if norm not in unique:
            unique[norm] = concept

    return list(unique.values())[:n]

# Test Cases
test_channels = [
    {
        "name": "ArjanCodes",
        "description": "Professional Python programming and software design tutorials for developers."
    },
    {
        "name": "Back To Back SWE",
        "description": "Technical interview preparation for software engineering roles at FAANG companies."
    },
    {
        "name": "Scottbez1",
        "description": "Hardware projects and embedded systems programming with Arduino and Raspberry Pi."
    },
    {
      "name": "Alex Lee",
      "description": "Learn Java!"
    },
    {
      "name": "minutephysics",
      "description": "Simply put: cool physics and other sweet science.\n\n\"If you can't explain it simply, you don't understand it well enough.\"\n~Rutherford via Einstein? (wikiquote)\n\nCreated by Henry Reich"
    },
    {
      "name": "Michael Sambol",
      "description": "Data structures and algorithms in X minutes.\n\nHowdy, I'm Mike. I'm a software engineer from the United States. I make concise computer science tutorials to help you learn, review for exams, and prep for interviews.\n\nMy background: I have a bachelor's and master's degree in computer science from Georgia Tech. I'm a principal software engineer for Workday, and I previously worked for AWS, Intuit, and IBM.",
    },
    {
      "name": "Gonkee",
      "description": "200 IQ big brain forefront of academia"
    },
    {
      "name": "Uncharted Foodie | Carlos Bradley",
      "description":  "I make videos about food, travel, and wine."
    },
    {
      "name": "MIT OpenCourseWare",
      "description": "A free and open online publication of educational material from thousands of MIT courses, covering the entire MIT curriculum, ranging from introductory to the most advanced graduate courses. On the OCW website, each course includes a syllabus, instructional material like notes and reading lists, and learning activities like assignments and solutions. Some courses also have videos, online textbooks, and faculty insights on teaching.\n\nKnowledge is your reward. There's no signup or enrollment, and no start or end dates. OCW is self-paced learning at its best. \n\nWhether you\u2019re a student, a teacher, or simply a curious person that wants to learn, MIT OpenCourseWare (OCW) offers a wealth of insight, inspiration, videos, and a whole lot more! \n\nGet the full picture on the OCW website at https://ocw.mit.edu.\n\nAccessibility: https://accessibility.mit.edu/ \n\nUser comments policy:  https://ocw.mit.edu/comments/\n\n(Channel banner photo by Nietnagel on Flickr: https://flic.kr/p/8WXxfK.)"
    }
]

for channel in test_channels:
    print(f"\nChannel: {channel['name']}")
    print("Description:", channel['description'])
    print("Inferred Topics:")
    topics=infer_topics(channel['name'], channel['description'])
    for i, topic in enumerate(topics, 1):
      print(f"{i}. {topic.capitalize()}")
      print("="*60)
