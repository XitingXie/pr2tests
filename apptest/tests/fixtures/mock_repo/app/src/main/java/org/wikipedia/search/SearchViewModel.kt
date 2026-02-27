package org.wikipedia.search

import androidx.lifecycle.ViewModel
import androidx.lifecycle.MutableLiveData

class SearchViewModel(
    private val repository: SearchRepository
) : ViewModel() {
    val results = MutableLiveData<List<SearchResultItem>>()

    fun search(query: String) {
        val items = repository.search(query)
        results.postValue(items)
    }
}
