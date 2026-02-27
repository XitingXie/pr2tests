package org.wikipedia.search

import android.view.ViewGroup
import androidx.recyclerview.widget.RecyclerView

class SearchAdapter : RecyclerView.Adapter<SearchAdapter.ViewHolder>() {
    private var items: List<SearchResultItem> = emptyList()

    fun submitList(newItems: List<SearchResultItem>) {
        items = newItems
        notifyDataSetChanged()
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): ViewHolder {
        TODO()
    }

    override fun onBindViewHolder(holder: ViewHolder, position: Int) {
        TODO()
    }

    override fun getItemCount() = items.size

    class ViewHolder(view: android.view.View) : RecyclerView.ViewHolder(view)
}
