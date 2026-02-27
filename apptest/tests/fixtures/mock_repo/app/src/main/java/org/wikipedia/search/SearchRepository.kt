package org.wikipedia.search

class SearchRepository(
    private val api: SearchApi
) {
    fun search(query: String): List<SearchResultItem> {
        return api.search(query).map { SearchResultItem(it.title, it.description) }
    }
}
