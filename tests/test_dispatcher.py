from app.dispatcher import classify_task


def test_routes_rename_prompt_to_organizer():
    assert classify_task("rename the doc1 files in my Downloads folder") == "organizer"


def test_routes_organize_documents_prompt_to_organizer():
    assert classify_task("organize the documents on my desktop") == "organizer"


def test_routes_tidy_up_prompt_to_organizer():
    assert classify_task("can you tidy up the files in Documents") == "organizer"


def test_routes_plain_search_prompt_to_browser():
    assert classify_task("search for flights from Hyderabad to Goa") == "browser"


def test_routes_navigation_prompt_to_browser():
    assert classify_task("open wikipedia and find the population of Hyderabad") == "browser"


def test_noun_alone_does_not_trigger_organizer():
    # "folder" is an organizer noun, but there's no organizer verb here --
    # this is still a browsing task and must not be misrouted.
    assert classify_task("find me a folder of recipe websites") == "browser"


def test_verb_alone_does_not_trigger_organizer():
    # "sort" is an organizer verb, but with no organizer noun this shouldn't
    # be enough on its own to route away from browsing.
    assert classify_task("sort the search results by price on Amazon") == "browser"


def test_amazon_price_search_is_not_misrouted():
    # regression case: this was the actual bug that motivated the matcher
    # rewrite earlier in this project -- make sure organizer routing doesn't
    # reintroduce a similar false-positive class of bug.
    assert classify_task("find the cheapest wireless mouse on amazon") == "browser"


def test_case_insensitive():
    assert classify_task("RENAME THE FILES IN DOWNLOADS") == "organizer"


def test_empty_prompt_routes_to_browser():
    assert classify_task("") == "browser"
