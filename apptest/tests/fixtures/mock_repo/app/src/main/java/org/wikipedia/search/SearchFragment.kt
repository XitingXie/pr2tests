package org.wikipedia.search

import android.os.Bundle
import androidx.fragment.app.Fragment
import androidx.fragment.app.viewModels

class SearchFragment : Fragment() {
    private val viewModel: SearchViewModel by viewModels()
    private lateinit var adapter: SearchAdapter

    override fun onViewCreated(view: android.view.View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)
        adapter = SearchAdapter()
        viewModel.results.observe(viewLifecycleOwner) { items ->
            adapter.submitList(items)
        }
    }
}
