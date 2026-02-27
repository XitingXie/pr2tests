package org.wikipedia.search

interface SearchApi {
    fun search(query: String): List<SearchApiResponse>
}

data class SearchApiResponse(
    val title: String,
    val description: String
)
