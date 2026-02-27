package org.wikipedia.page

import android.os.Bundle
import androidx.appcompat.app.AppCompatActivity

class PageActivity : AppCompatActivity() {
    private lateinit var viewModel: PageViewModel

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        viewModel = PageViewModel()
    }
}
