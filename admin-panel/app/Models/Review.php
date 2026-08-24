<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;

class Review extends Model
{
    protected $connection = 'exchange';
    protected $table = 'reviews';
    public $timestamps = false;

    protected $fillable = ['status'];
}
