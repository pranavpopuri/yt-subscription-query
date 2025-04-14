import re
import nltk
from collections import Counter
from nltk.corpus import wordnet, stopwords
from nltk.tokenize import word_tokenize, sent_tokenize
from nltk.tag import pos_tag
from nltk.stem import WordNetLemmatizer

# Initialize NLP resources
nltk.download(['punkt', 'averaged_perceptron_tagger',
              'wordnet', 'stopwords'], quiet=True)
lemmatizer = WordNetLemmatizer()
stop_words = set(stopwords.words('english'))


def contextual_topic_expansion(text):
    """Analyze text to discover semantically related concepts"""
    # Extract core entities
    entities = extract_core_entities(text)

    # Expand each entity with related concepts
    expanded_topics = set()
    for entity in entities:
        expanded_topics.add(entity)

        # Get semantic relations from WordNet
        for synset in wordnet.synsets(entity, pos='n'):
            # Hypernyms (more general concepts)
            for hyper in synset.hypernyms()[:2]:
                expanded_topics.update(lemma.name().replace(
                    '_', ' ') for lemma in hyper.lemmas())

            # Hyponyms (more specific concepts)
            for hypo in synset.hyponyms()[:2]:
                expanded_topics.update(lemma.name().replace(
                    '_', ' ') for lemma in hypo.lemmas())

            # Meronyms (part-whole relationships)
            for mero in synset.part_meronyms()[:2]:
                expanded_topics.update(lemma.name().replace(
                    '_', ' ') for lemma in mero.lemmas())

    return filter_and_rank_topics(expanded_topics, text)


def extract_core_entities(text):
    """Identify the most important named entities and noun phrases"""
    sentences = sent_tokenize(text)
    grammar = r"""
        ENTITY: {<NNP>+}
        CONCEPT: {<JJ>*<NN.*>+}
    """
    chunker = nltk.RegexpParser(grammar)

    entities = set()
    for sentence in sentences:
        words = word_tokenize(sentence)
        tagged = pos_tag(words)
        tree = chunker.parse(tagged)

        for subtree in tree.subtrees():
            if subtree.label() in ['ENTITY', 'CONCEPT']:
                phrase = ' '.join(word.lower() for word, tag in subtree.leaves()
                                  if word.lower() not in stop_words and len(word) > 2)
                if 3 <= len(phrase) <= 25:
                    entities.add(phrase)

    return entities


def filter_and_rank_topics(topics, context):
    """Score and filter topics based on contextual relevance"""
    scored = []
    context_words = set(word_tokenize(context.lower()))

    for topic in topics:
        # Basic validity checks
        if (not topic or
            any(word in stop_words for word in topic.split()) or
                len(topic) < 3):
            continue

        # Relevance scoring
        score = 0
        topic_words = set(word_tokenize(topic.lower()))

        # Term frequency in original context
        score += sum(1 for word in topic_words if word in context_words) * 2

        # Specificity bonus
        if any(tag.startswith('NNP') for word, tag in pos_tag(word_tokenize(topic))):
            score += 3

        # Length adjustment
        score += min(len(topic.split()), 3)  # Prefer 1-3 word phrases

        # Semantic density (unique words per length)
        score += len(set(topic_words)) / len(topic_words)

        scored.append((score, topic))

    # Sort by score and remove duplicates
    scored.sort(reverse=True)
    seen = set()
    final_topics = []
    for score, topic in scored:
        norm_topic = ' '.join(sorted(topic.split()))
        if norm_topic not in seen:
            seen.add(norm_topic)
            final_topics.append(topic)

    return final_topics


def generate_topics(name, description, n=10):
    """Generate semantically expanded topics"""
    text = f"{name} {description}"
    topics = contextual_topic_expansion(text)

    # Ensure we have enough topics
    if len(topics) < n:
        # Fallback to basic extraction if semantic expansion fails
        base_entities = extract_core_entities(text)
        topics = list(base_entities) + topics

    return topics[:n]


# Test Cases
channels = [
    {
        "name": "ArjanCodes",
        "description": "Professional Python programming and software design tutorials for developers."
    },
    {
        "name": "WildlifeFilmmaking",
        "description": "Documentary film techniques for capturing animal behavior in natural habitats."
    },
    {
        "name": "VintageCarRestoration",
        "description": "Step-by-step guides for restoring classic automobiles from the 1960s-1980s."
    }
]

for channel in channels:
    print(f"\nChannel: {channel['name']}")
    topics = generate_topics(channel['name'], channel['description'])
    print("Core Topics:")
    for i, topic in enumerate(topics, 1):
        print(f"{i}. {topic.capitalize()}")
    print("="*60)
