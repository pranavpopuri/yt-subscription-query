import re
import nltk
from nltk.corpus import wordnet, stopwords
from nltk.tokenize import word_tokenize, sent_tokenize
from nltk.tag import pos_tag
from nltk.stem import WordNetLemmatizer
from sklearn.feature_extraction.text import TfidfVectorizer


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


def contextual_topic_expansion(text):
    """Analyze text to discover semantically related concepts"""
    entities = extract_core_entities(text)
    expanded_topics = set()

    for entity in entities:
        expanded_topics.add(entity)
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


def filter_and_rank_topics(topics, context):
    """Score and filter topics based on contextual relevance"""
    scored = []
    context_words = set(word_tokenize(context.lower()))

    for topic in topics:
        if (not topic or
            any(word in stop_words for word in topic.split()) or
                len(topic) < 3):
            continue

        score = 0
        topic_words = set(word_tokenize(topic.lower()))

        # Term frequency in original context
        score += sum(1 for word in topic_words if word in context_words) * 2

        # Specificity bonus
        if any(tag.startswith('NNP') for word, tag in pos_tag(word_tokenize(topic))):
            score += 3

        # Length adjustment
        score += min(len(topic.split()), 3)

        # Semantic density
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


def generate_channel_keywords(name, description, n=10):
    """Generate high-quality, semantically expanded keywords for a channel"""
    text = f"{name} {description}"
    processed_text = preprocess_text(text)

    # Step 1: Extract candidate keywords using TF-IDF
    vectorizer = TfidfVectorizer(stop_words="english", max_features=50)
    tfidf_matrix = vectorizer.fit_transform([processed_text])
    feature_names = vectorizer.get_feature_names_out()
    tfidf_scores = tfidf_matrix.toarray()[0]

    # Combine terms and scores
    tfidf_keywords = {feature_names[i]: tfidf_scores[i]
                      for i in range(len(feature_names))}

    # Step 2: Expand keywords with semantic relationships
    expanded_keywords = set()
    for keyword in tfidf_keywords.keys():
        expanded_keywords.add(keyword)
        for synset in wordnet.synsets(keyword, pos='n'):
            expanded_keywords.update(lemma.name().replace(
                '_', ' ') for lemma in synset.lemmas())

    # Step 3: Filter and rank keywords
    filtered_keywords = []
    for keyword in expanded_keywords:
        if keyword in stop_words or len(keyword) < 3:
            continue
        if keyword in processed_text:
            filtered_keywords.append(keyword)

    # Rank keywords by their TF-IDF scores
    ranked_keywords = sorted(
        filtered_keywords, key=lambda k: tfidf_keywords.get(k, 0), reverse=True)

    return ranked_keywords[:n]
